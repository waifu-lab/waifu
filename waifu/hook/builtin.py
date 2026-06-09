import re
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Dict, List, Optional

from waifu.logger import logger
from waifu_types import BaseHook, HookContext, SystemPromptLayers

if TYPE_CHECKING:
    from waifu.voice.service import VoiceService


class RateLimitHook(BaseHook):
    """
    per-conversation 滑動視窗限流

    超過 max_rpm 時設 ctx.abort=True 並回傳提示訊息
    """

    name = "rate_limit"
    priority = 0

    def __init__(self, max_rpm: int = 60, message: str = "請求太頻繁，請稍後再試") -> None:
        self._max_rpm = max_rpm
        self._window = 60.0
        self._message = message

        self._records: Dict[str, List[float]] = defaultdict(list)

    async def pre(self, ctx: HookContext) -> HookContext:
        cid = ctx.request.conversation_id
        now = time.monotonic()
        window_start = now - self._window

        self._records[cid] = [t for t in self._records[cid] if t > window_start]

        if len(self._records[cid]) >= self._max_rpm:
            ctx.abort = True
            ctx.response = self._message
            logger.warning("Rate limit hit: {} ({} rpm)", cid, len(self._records[cid]))
        else:
            self._records[cid].append(now)

        return ctx


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

    def contribute_prompt(self, ctx: HookContext, layers: SystemPromptLayers) -> None:
        if not ctx.request.live2d:
            return
        expressions = ctx.session.metadata.get("live2d_expressions") or sorted(set(self._emotion_map.values()))
        options = ", ".join(expressions)
        layers.output_discipline.append(
            f"## 情緒表達\n"
            f"在每一句話的開頭加上情緒標籤，格式為 [emotion:xxx]，從以下選項中選擇：{options}\n"
            f"範例：[emotion:happy]今天天氣真好！[emotion:sad]但我有點擔心你。"
        )

    async def mid(self, ctx: HookContext) -> HookContext:
        """存入 history 前清除 new_messages 裡的 emotion tag。"""
        for msg in ctx.new_messages:
            if msg.role == "assistant" and msg.content:
                msg.content = _EMOTION_TAG_PATTERN.sub("", msg.content).strip()
        return ctx

    async def post(self, ctx: HookContext) -> HookContext:
        if not ctx.response or not ctx.request.live2d:
            return ctx

        # 若 TTSHook 已處理逐句 emotion，跳過獨立事件
        if ctx.metadata.get("tts_emotion_handled"):
            return ctx

        live2d_expressions: list = ctx.session.metadata.get("live2d_expressions", [])
        allowed = live2d_expressions or None
        for emotion in self._detect_all(ctx.response, allowed):
            ctx.events.append({"event": "emotion", "data": {"emotion": emotion}})
        return ctx

    def _detect_all(self, text: str, allowed: Optional[List[str]] = None) -> List[str]:
        tags = _EMOTION_TAG_PATTERN.findall(text)
        if tags:
            result = [
                e
                for tag in tags
                if (e := self._emotion_map.get(tag.lower(), tag.lower())) and (allowed is None or e in allowed)
            ]
            if result:
                return result
        return [self._detect(text, allowed)]

    def _detect(self, text: str, allowed: Optional[List[str]] = None) -> str:
        # 優先：明確標籤（第一個）
        match = _EMOTION_TAG_PATTERN.search(text)
        if match:
            tag = match.group(1).lower()
            emotion = self._emotion_map.get(tag, tag)
            if allowed is None or emotion in allowed:
                return emotion

        # 關鍵字掃描
        text_lower = text.lower()
        for keyword, emotion in self._emotion_map.items():
            if keyword.lower() in text_lower:
                if allowed is None or emotion in allowed:
                    return emotion

        if allowed and self._default_emotion not in allowed:
            return allowed[0]
        return self._default_emotion


class LoggingHook(BaseHook):
    """
    記錄每次請求的來源、對話 ID、回應長度與 trace 資訊

    pre：記錄請求開始時間
    post：記錄完整耗時與 trace
    """

    name = "logging"
    priority = 100  # 最後執行

    def __init__(self, log_level: str = "INFO") -> None:
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
            logger.debug("trace: {}", ctx.trace)

        return ctx


class TTSHook(BaseHook):
    """
    語音合成 Hook（post）

    在 agent 回應後，切句逐句呼叫 VoiceService.synthesize_sentences()，
    每句產出帶 emotion 的 audio 事件，前端播放時同步切換表情。

    若傳入 emotion_hook，會對每句做 emotion 偵測並將結果塞入 audio 事件 data，
    同時標記 tts_emotion_handled 讓 EmotionHook 跳過獨立事件。

    Discord / Telegram adapter 不支援音訊事件，此 hook 對其無副作用。
    """

    name = "tts"
    priority = 15  # 在 EmotionHook 之前

    def __init__(
        self,
        voice_service: "VoiceService",
        emotion_hook: Optional["EmotionHook"] = None,
    ) -> None:
        self._voice = voice_service
        self._emotion_hook = emotion_hook

    async def post(self, ctx: HookContext) -> HookContext:
        if not ctx.response or not ctx.request.live2d:
            return ctx

        try:
            live2d_expressions: list = ctx.session.metadata.get("live2d_expressions", [])
            allowed = live2d_expressions or None

            async for result in self._voice.synthesize_sentences(ctx.response, need_lipsync=ctx.request.need_lipsync):
                emotion: Optional[str] = None
                if self._emotion_hook is not None:
                    emotion = self._emotion_hook._detect(result.sentence, allowed)
                    result.sentence = _EMOTION_TAG_PATTERN.sub("", result.sentence).strip()

                if emotion is not None:
                    await ctx.request.reply_fn(event={"event": "emotion", "data": {"emotion": emotion}})
                for ev in self._voice.build_audio_events(result, emotion=emotion):
                    await ctx.request.reply_fn(event=ev)

            if self._emotion_hook is not None:
                ctx.metadata["tts_emotion_handled"] = True

        except Exception:
            logger.exception("TTSHook: synthesis failed")

        return ctx


__all__ = [
    "RateLimitHook",
    "EmotionHook",
    "LoggingHook",
    "TTSHook",
]
