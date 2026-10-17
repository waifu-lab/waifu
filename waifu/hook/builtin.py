import asyncio
import time
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Sequence

from waifu.logger import logger
from waifu_types import (
    BaseHook,
    Event,
    Feature,
    HookContext,
    InlineTagTransformer,
    OutputTransformer,
    SessionMeta,
    SpanMarkerTransformer,
    SpanPiece,
    StreamObserver,
    SystemPromptLayers,
)

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

        self._records: Dict[str, List[float]] = {}

    async def pre(self, ctx: HookContext) -> HookContext:
        cid = ctx.request.conversation_id
        now = time.monotonic()
        window_start = now - self._window

        self._prune(window_start)
        records = self._records.setdefault(cid, [])

        if len(records) >= self._max_rpm:
            ctx.abort = True
            ctx.response = self._message
            logger.warning("Rate limit hit: {} ({} rpm)", cid, len(records))
        else:
            records.append(now)

        return ctx

    def _prune(self, window_start: float) -> None:
        for cid in list(self._records):
            kept = [t for t in self._records[cid] if t > window_start]
            if kept:
                self._records[cid] = kept
            else:
                del self._records[cid]


EMOTION = "emotion"


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


def allowed_expressions(ctx: HookContext) -> Optional[List[str]]:
    """前端 live2dsync 回報的可用表情；未回報時為 None（不限制）"""
    return ctx.session.metadata.get(SessionMeta.LIVE2D_EXPRESSIONS) or None


class EmotionHook(BaseHook):
    name = "emotion"
    priority = 20

    def __init__(
        self,
        emotion_map: Optional[Dict[str, str]] = None,
        default_emotion: str = "neutral",
    ) -> None:
        self._emotion_map = emotion_map or _DEFAULT_EMOTION_MAP
        self._default_emotion = default_emotion
        self._tags = InlineTagTransformer(EMOTION, [EMOTION])

    def output_transformers(self) -> Sequence[OutputTransformer]:
        return (self._tags,)

    def contribute_prompt(self, ctx: HookContext, layers: SystemPromptLayers) -> None:
        if not ctx.request.has_feature(Feature.LIVE2D):
            return
        expressions = allowed_expressions(ctx) or sorted(set(self._emotion_map.values()))
        options = ", ".join(expressions)
        layers.output_discipline.append(
            f"## 情緒表達\n"
            f"在每一句話的開頭加上情緒標籤，格式為 [emotion:xxx]，從以下選項中選擇：{options}\n"
            f"範例：[emotion:happy]今天天氣真好！[emotion:sad]但我有點擔心你。"
        )

    async def post(self, ctx: HookContext) -> HookContext:
        if not ctx.response or not ctx.request.has_feature(Feature.LIVE2D) or EMOTION in ctx.handled:
            return ctx

        for emotion in self.detect_all(ctx.response, allowed_expressions(ctx)):
            ctx.emit(Event(event=EMOTION, data={"emotion": emotion}))
        ctx.handled.add(EMOTION)
        return ctx

    def detect_all(self, text: str, allowed: Optional[List[str]] = None) -> List[str]:
        """回傳文字中所有情緒標籤（依出現順序）；沒有標籤時以 detect() 推測一個"""
        result = [
            e
            for tag in self._tags.find(text)
            if (e := self._emotion_map.get(tag.value.lower(), tag.value.lower())) and (allowed is None or e in allowed)
        ]
        return result or [self.detect(text, allowed)]

    def detect(self, text: str, allowed: Optional[List[str]] = None) -> str:
        """推測一段文字的情緒：優先使用第一個標籤，其次關鍵字，最後為預設情緒"""
        tag = self._tags.first(text)
        if tag is not None:
            emotion = self._emotion_map.get(tag.value.lower(), tag.value.lower())
            if allowed is None or emotion in allowed:
                return emotion

        text_lower = text.lower()
        for keyword, emotion in self._emotion_map.items():
            if keyword.lower() in text_lower and (allowed is None or emotion in allowed):
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
            "[PRE] request={} conv={} source={}",
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
            "[POST] request={} conv={} elapsed={:.2f}s resp_len={}",
            rid,
            ctx.request.conversation_id,
            elapsed,
            resp_len,
        )

        if ctx.trace is not None:
            logger.debug("trace: {}", ctx.trace)

        return ctx


SPEAK = "speak"


class TTSHook(BaseHook):
    name = "tts"
    priority = 15  # 在 EmotionHook 之前

    def __init__(
        self,
        voice_service: "VoiceService",
        clean: Callable[[str], str],
        emotion_hook: Optional[EmotionHook] = None,
    ) -> None:
        self._voice = voice_service
        self._clean = clean
        self._emotion_hook = emotion_hook
        self._speak = SpanMarkerTransformer(SPEAK, SPEAK)

    def output_transformers(self) -> Sequence[OutputTransformer]:
        return (self._speak,)

    def contribute_prompt(self, ctx: HookContext, layers: SystemPromptLayers) -> None:
        if not ctx.request.has_feature(Feature.LIVE2D):
            return
        layers.output_discipline.append(
            "## 語音朗讀（必須遵守）\n"
            "你的回覆會用語音唸出來。\n"
            "- 純聊天、沒有程式碼 / 清單 / 表格 / 網址的短回覆：直接回覆，不加標記，整段都會唸。\n"
            "- 只要回覆裡有程式碼、指令、清單、表格、網址、步驟、查詢結果整理其中任何一項："
            "回覆的第一個字元必須是 [speak]。把要唸出來的話寫成一兩句簡短口語包在 [speak]...[/speak] 內，"
            "其餘內容放在區段外，只顯示不唸。[speak] 區段內不可放程式碼、網址或清單。\n"
            "範例一（程式碼）：\n"
            "[speak]用內建的 json 模組就可以讀，範例放在下面。[/speak]\n"
            "```python\nimport json\n...\n```\n"
            "範例二（查詢結果）：\n"
            "[speak]查到了，重點有三個，我整理在下面。[/speak]\n1. ...\n2. ...\n3. ...\n"
            "[speak]需要的話我可以再說明第二點。[/speak]"
        )

    def stream_observer(self, ctx: HookContext) -> Optional[StreamObserver]:
        if not ctx.request.has_feature(Feature.LIVE2D):
            return None
        return _TTSStreamObserver(ctx, self._voice, self._clean, self._emotion_hook, self._speak)


class _TTSStreamObserver(StreamObserver):
    """LLM 串流時邊切句邊合成；每句合成好就依序送出 emotion → audio → lipsync"""

    def __init__(
        self,
        ctx: HookContext,
        voice_service: "VoiceService",
        clean: Callable[[str], str],
        emotion_hook: Optional[EmotionHook],
        speak: SpanMarkerTransformer,
    ) -> None:
        self._ctx = ctx
        self._voice = voice_service
        self._clean = clean
        self._emotion_hook = emotion_hook
        self._speak = speak
        self._stream = voice_service.sentence_stream(
            need_lipsync=ctx.request.has_feature(Feature.LIPSYNC),
            clean=clean,
        )
        self._new_turn()
        self._sender = asyncio.create_task(self._send())

    def _new_turn(self) -> None:
        self._splitter = self._speak.splitter()
        # None：還沒看到實際內容，尚未判斷；True：本輪只唸 [speak] 區段；False：本輪全唸
        self._tagged: Optional[bool] = None
        self._head = ""  # 判斷前的前綴（只會是空白 / 其他標籤，例如 [emotion:happy]）

    def feed(self, chunk: str) -> None:
        self._route(self._splitter.feed(chunk))

    def end_turn(self) -> None:
        self._route(self._splitter.flush())
        self._stream.end_turn()
        self._new_turn()

    def reset(self) -> None:
        self._stream.reset()
        self._new_turn()

    async def finish(self) -> None:
        self._route(self._splitter.flush())
        self._stream.close()
        await self._sender

    def _route(self, pieces: List[SpanPiece]) -> None:
        for piece in pieces:
            if self._tagged is None:
                self._decide(piece)
            elif not self._tagged:
                self._stream.feed(piece.text)
            elif piece.marker:
                if not piece.inside:
                    self._stream.break_sentence()
            elif piece.inside:
                self._stream.feed(piece.text)

    def _decide(self, piece: SpanPiece) -> None:
        if piece.marker:
            self._tagged = True
            if piece.inside:
                self._stream.feed(self._head)
            self._head = ""
            return
        self._head += piece.text
        if self._clean(self._head).strip():
            self._tagged = False
            self._stream.feed(self._head)
            self._head = ""

    async def aclose(self) -> None:
        self._sender.cancel()
        await self._stream.aclose()
        await asyncio.gather(self._sender, return_exceptions=True)

    async def _send(self) -> None:
        ctx = self._ctx
        emotion_hook = self._emotion_hook
        allowed = allowed_expressions(ctx)
        try:
            async for result in self._stream.results():
                if emotion_hook is not None:
                    emotion = emotion_hook.detect(result.sentence, allowed)
                    await ctx.request.reply_event(Event(event=EMOTION, data={"emotion": emotion}))
                    ctx.handled.add(EMOTION)
                for ev in self._voice.build_audio_events(result):
                    await ctx.request.reply_event(ev)
        except Exception:
            logger.exception("TTSHook: synthesis failed")


__all__ = [
    "EMOTION",
    "SPEAK",
    "RateLimitHook",
    "EmotionHook",
    "LoggingHook",
    "TTSHook",
    "allowed_expressions",
]
