import logging
import re
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol, runtime_checkable

from waifu_types import AssistantMessage, BaseHook, BaseMessage, ConversationMode, HookContext, UserMessage

if TYPE_CHECKING:
    from waifu.voice.service import VoiceService


@runtime_checkable
class MemoryStore(Protocol):
    async def load(self, key: str) -> List[BaseMessage]: ...
    async def save(self, key: str, messages: List[BaseMessage]) -> None: ...


logger = logging.getLogger(__name__)


class RateLimitHook(BaseHook):
    """
    per-conversation 滑動視窗限流

    超過 max_rpm 時設 ctx.abort=True 並回傳提示訊息
    """

    name = "rate_limit"
    priority = 0  # 最早執行，避免浪費後續運算

    def __init__(self, max_rpm: int = 60, message: str = "請求太頻繁，請稍後再試") -> None:
        self._max_rpm = max_rpm
        self._window = 60.0
        self._message = message
        # conversation_id → [timestamp, ...]
        self._records: Dict[str, List[float]] = defaultdict(list)

    async def pre(self, ctx: HookContext) -> HookContext:
        cid = ctx.request.conversation_id
        now = time.monotonic()
        window_start = now - self._window

        # 清除視窗外的舊記錄
        self._records[cid] = [t for t in self._records[cid] if t > window_start]

        if len(self._records[cid]) >= self._max_rpm:
            ctx.abort = True
            ctx.response = self._message
            logger.warning("Rate limit hit: %s (%d rpm)", cid, len(self._records[cid]))
        else:
            self._records[cid].append(now)

        return ctx


class MemoryHook(BaseHook):
    """
    對話歷史持久化 Hook

    pre ：從外部 store 載入歷史，注入 ctx.messages；若 store 支援關係層，注入 ctx.metadata
    post：將本輪新訊息寫回 store

    store 介面（duck typing）：
        async def load(key: str) -> List[Dict]
        async def save(key: str, messages: List[Dict]) -> None
        async def get_relationship(key: str) -> str  (optional)

    預設使用內建的 InMemoryStore（無持久化，重啟清空）
    傳入 FileMemoryStore / Redis / SQLite store 即可替換
    """

    name = "memory"
    priority = 10

    def __init__(self, store: Optional[MemoryStore] = None, max_history: int = 50) -> None:
        self._store = store or InMemoryStore()
        self._max_history = max_history

    async def pre(self, ctx: HookContext) -> HookContext:
        cid = ctx.request.conversation_id
        history = await self._store.load(cid)
        if history:
            ctx.messages = list(history)

        if hasattr(self._store, "get_relationship"):
            await self._inject_relationship(ctx)

        return ctx

    async def post(self, ctx: HookContext) -> HookContext:
        if ctx.response is None:
            return ctx

        cid = ctx.request.conversation_id
        existing = await self._store.load(cid)

        new_messages: List[BaseMessage] = [
            UserMessage(content=ctx.request.content),
            AssistantMessage(content=ctx.response),
        ]
        merged = (existing or []) + new_messages

        if len(merged) > self._max_history:
            merged = merged[-self._max_history:]

        await self._store.save(cid, merged)
        return ctx

    async def _inject_relationship(self, ctx: HookContext) -> None:
        """從 store 取得關係層，注入 ctx.metadata["relationship"]"""
        if ctx.request.mode == ConversationMode.session:
            return

        direct_key = f"{ctx.request.source}:dm:{ctx.request.sender.user_id}"
        relationship = await self._store.get_relationship(direct_key)
        if relationship:
            ctx.metadata["relationship"] = relationship


class InMemoryStore:
    """簡易 in-memory 歷史 store（預設，重啟清空）"""

    def __init__(self) -> None:
        self._data: Dict[str, List[BaseMessage]] = {}

    async def load(self, key: str) -> List[BaseMessage]:
        return list(self._data.get(key, []))

    async def save(self, key: str, messages: List[BaseMessage]) -> None:
        self._data[key] = list(messages)


# 支援的情緒關鍵字映射（可在子類覆寫）
_DEFAULT_EMOTION_MAP: Dict[str, str] = {
    "happy": "happy",
    "開心": "happy",
    "高興": "happy",
    "喜歡": "happy",
    "sad": "sad",
    "難過": "sad",
    "傷心": "sad",
    "哭": "sad",
    "angry": "angry",
    "生氣": "angry",
    "憤怒": "angry",
    "surprised": "surprised",
    "驚訝": "surprised",
    "吃驚": "surprised",
    "shy": "shy",
    "害羞": "shy",
}

_EMOTION_TAG_PATTERN = re.compile(r"\[emotion:(\w+)\]", re.IGNORECASE)


class EmotionHook(BaseHook):
    """
    從 assistant 回應中解析情緒，寫入 ctx.events 供前端（Live2D）使用

    解析方式（依優先順序）：
    1. 明確標籤：回應中含 [emotion:happy] 等標記（需 LLM 在 system prompt 中被指示輸出）
    2. 關鍵字掃描：在回應文字中掃描 emotion_map 的關鍵字
    """

    name = "emotion"
    priority = 20

    def __init__(
        self,
        emotion_map: Optional[Dict[str, str]] = None,
        default_emotion: str = "neutral",
    ) -> None:
        self._emotion_map = emotion_map or _DEFAULT_EMOTION_MAP
        self._default_emotion = default_emotion

    async def post(self, ctx: HookContext) -> HookContext:
        if not ctx.response or not ctx.request.live2d:
            return ctx

        emotion = self._detect(ctx.response)
        ctx.events.append({"event": "emotion", "data": {"emotion": emotion}})
        return ctx

    def _detect(self, text: str) -> str:
        # 優先：明確標籤
        match = _EMOTION_TAG_PATTERN.search(text)
        if match:
            tag = match.group(1).lower()
            return self._emotion_map.get(tag, tag)

        # 關鍵字掃描
        text_lower = text.lower()
        for keyword, emotion in self._emotion_map.items():
            if keyword.lower() in text_lower:
                return emotion

        return self._default_emotion


class LoggingHook(BaseHook):
    """
    記錄每次請求的來源、對話 ID、回應長度與 trace 資訊

    pre：記錄請求開始時間
    post：記錄完整耗時與 trace
    """

    name = "logging"
    priority = 100  # 最後執行

    def __init__(self, log_level: int = logging.INFO) -> None:
        self._level = log_level
        self._start_times: Dict[str, float] = {}

    async def pre(self, ctx: HookContext) -> HookContext:
        self._start_times[ctx.request.request_id] = time.monotonic()
        logger.log(
            self._level,
            "[%s] request=%s conv=%s source=%s",
            "PRE",
            ctx.request.request_id,
            ctx.request.conversation_id,
            ctx.request.source,
        )
        return ctx

    async def post(self, ctx: HookContext) -> HookContext:
        rid = ctx.request.request_id
        elapsed = time.monotonic() - self._start_times.pop(rid, time.monotonic())
        resp_len = len(ctx.response or "")

        logger.log(
            self._level,
            "[%s] request=%s conv=%s elapsed=%.2fs resp_len=%d",
            "POST",
            rid,
            ctx.request.conversation_id,
            elapsed,
            resp_len,
        )

        if ctx.trace is not None:
            logger.debug("trace: %s", ctx.trace)

        return ctx


class TTSHook(BaseHook):
    """
    語音合成 Hook（post）

    在 agent 回應後，呼叫 VoiceService.synthesize() 將文字轉為音訊，
    並將 audio 事件與 lipsync 事件寫入 ctx.events，
    由 WebSocketAdapter 隨其他事件一併送出

    Discord / Telegram adapter 不支援音訊事件，此 hook 對其無副作用
    """

    name = "tts"
    priority = 15  # 在 EmotionHook 之前

    def __init__(self, voice_service: "VoiceService") -> None:
        self._voice = voice_service

    async def post(self, ctx: HookContext) -> HookContext:
        if not ctx.response or not ctx.request.live2d:
            return ctx

        try:
            result = await self._voice.synthesize(ctx.response)
            events = self._voice.build_audio_events(result)
            ctx.events.extend(events)
        except Exception:
            logger.exception("TTSHook: synthesis failed")

        return ctx


__all__ = [
    "RateLimitHook",
    "MemoryHook",
    "InMemoryStore",
    "EmotionHook",
    "LoggingHook",
    "TTSHook",
]
