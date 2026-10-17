import asyncio
import base64
import re
from typing import TYPE_CHECKING, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Protocol, Set

import httpx

from waifu.logger import logger
from waifu_types import Event

from .lipsync import build_lipsync_events

if TYPE_CHECKING:
    from hai.providers.providers import ProviderSTT

    from waifu.config import VoiceConfig

    from .translator import DeepLTranslator

_SENTENCE_SPLIT = re.compile(
    r"(?<=[。！？!?…])\s+|(?<=[。！？!?…])(?=\S)|(?<=\.)\s+(?=(?:['\"([{<]|[A-Z0-9\u4e00-\u9fff]))"
)


class TTSProvider(Protocol):
    response_format: str

    async def synthesize(self, text: str) -> bytes: ...

    def synthesize_stream(self, text: str, chunk_size: int = 4096) -> AsyncIterator[bytes]: ...


class VoiceService:
    @classmethod
    def from_config(cls, config: "VoiceConfig") -> "VoiceService":
        return cls(
            stt=config.stt.build() if config.stt else None,
            tts=config.tts.build() if config.tts else None,
            lipsync_fps=config.lipsync_fps,
            tts_timeout_retries=config.tts.timeout_retries if config.tts else 0,
            tts_retry_backoff_s=config.tts.retry_backoff_s if config.tts else 0.0,
            tts_max_concurrency=config.tts.max_concurrency if config.tts else 1,
            translator=config.translation.build() if config.translation else None,
        )

    def __init__(
        self,
        stt: Optional["ProviderSTT"] = None,
        tts: Optional[TTSProvider] = None,
        lipsync_fps: int = 20,
        tts_timeout_retries: int = 2,
        tts_retry_backoff_s: float = 0.5,
        tts_max_concurrency: int = 2,
        translator: Optional["DeepLTranslator"] = None,
    ) -> None:
        self._stt = stt
        self._tts = tts
        self._lipsync_fps = lipsync_fps
        self._tts_timeout_retries = max(0, tts_timeout_retries)
        self._tts_retry_backoff_s = max(0.0, tts_retry_backoff_s)
        self._tts_max_concurrency = max(1, tts_max_concurrency)
        self._translator = translator

    @property
    def has_stt(self) -> bool:
        return self._stt is not None

    @property
    def has_tts(self) -> bool:
        return self._tts is not None

    async def transcribe(self, audio: bytes, format: str = "webm", language: Optional[str] = None) -> str:
        if self._stt is None:
            raise RuntimeError("VoiceService: STT provider not configured")
        return await self._stt.transcribe(audio, format=format, language=language)

    async def _translate(self, text: str) -> str:
        if self._translator is None:
            return text
        try:
            return await self._translator.translate(text)
        except Exception as exc:
            logger.warning("DeepL translation failed, using original text: {}", exc)
            return text

    async def synthesize(self, text: str, need_lipsync: bool = False) -> "SynthesisResult":
        if self._tts is None:
            raise RuntimeError("VoiceService: TTS provider not configured")

        text = await self._translate(text)
        audio_bytes = await self._tts.synthesize(text)
        fmt = self._tts.response_format
        visemes = build_lipsync_events(text, frames=self._lipsync_fps) if need_lipsync else []

        return SynthesisResult(
            audio_bytes=audio_bytes,
            format=fmt,
            lipsync_events=visemes,
        )

    async def synthesize_stream(self, text: str, chunk_size: int = 4096) -> AsyncIterator[bytes]:
        """逐塊 yield 音訊 bytes，不緩衝整段音頻。"""
        if self._tts is None:
            raise RuntimeError("VoiceService: TTS provider not configured")
        text = await self._translate(text)
        async for chunk in self._tts.synthesize_stream(text, chunk_size=chunk_size):
            yield chunk

    def sentence_stream(
        self,
        need_lipsync: bool = False,
        clean: Optional[Callable[[str], str]] = None,
    ) -> "SentenceStream":
        """邊收 LLM 文字邊切句合成；各句並行（上限 tts_max_concurrency），依原句順序取得結果"""
        if self._tts is None:
            raise RuntimeError("VoiceService: TTS provider not configured")

        async def _one(sentence: str) -> "SynthesisResult | None":
            return await self._synthesize_sentence(sentence, need_lipsync, clean)

        return SentenceStream(_one, self._tts_max_concurrency)

    # TODO: 尚未使用 synthesize_stream
    async def _synthesize_sentence(
        self,
        sentence: str,
        need_lipsync: bool,
        clean: Optional[Callable[[str], str]],
    ) -> "SynthesisResult | None":
        if self._tts is None:
            raise RuntimeError("VoiceService: TTS provider not configured")
        spoken = (clean(sentence) if clean is not None else sentence).strip()
        if not spoken:
            return None
        tts_text = await self._translate(spoken)
        audio_bytes = await self._synthesize_with_retry(sentence, tts_text)
        visemes = build_lipsync_events(spoken, frames=self._lipsync_fps) if need_lipsync else []
        return SynthesisResult(
            audio_bytes=audio_bytes,
            format=self._tts.response_format,
            lipsync_events=visemes,
            sentence=sentence,
        )

    async def _synthesize_with_retry(self, sentence: str, tts_text: str) -> bytes:
        if self._tts is None:
            raise RuntimeError("VoiceService: TTS provider not configured")
        attempts = self._tts_timeout_retries + 1

        for attempt in range(1, attempts + 1):
            try:
                return await self._tts.synthesize(tts_text)
            except httpx.TimeoutException as exc:
                if attempt >= attempts:
                    raise

                logger.warning(
                    "VoiceService: timeout synthesizing sentence {!r} (attempt {}/{}), retrying",
                    sentence[:80],
                    attempt,
                    attempts,
                )
                if self._tts_retry_backoff_s > 0:
                    await asyncio.sleep(self._tts_retry_backoff_s)

        raise RuntimeError("VoiceService: TTS retry loop exited without result")

    def build_audio_events(self, result: "SynthesisResult") -> List[Event]:
        audio_b64 = base64.b64encode(result.audio_bytes).decode()
        events = [Event(event="audio", data={"audio": audio_b64, "format": result.format})]
        if result.lipsync_events:
            events.append(Event(event="lipsync", data={"visemes": result.lipsync_events}))
        return events


class SynthesisResult:
    __slots__ = ("audio_bytes", "format", "lipsync_events", "sentence")

    def __init__(
        self,
        audio_bytes: bytes,
        format: str,
        lipsync_events: List[Dict],
        sentence: str = "",
    ) -> None:
        self.audio_bytes = audio_bytes
        self.format = format
        self.lipsync_events = lipsync_events
        self.sentence = sentence


class _PendingSentence:
    __slots__ = ("sentence", "task", "dropped")

    def __init__(self, sentence: str, task: "asyncio.Task[SynthesisResult | None]") -> None:
        self.sentence = sentence
        self.task = task
        self.dropped = False


class SentenceStream:
    def __init__(
        self,
        synthesize: Callable[[str], Awaitable["SynthesisResult | None"]],
        max_concurrency: int,
    ) -> None:
        self._synthesize = synthesize

        self._sem = asyncio.Semaphore(max_concurrency)
        self._buf = ""
        self._turn: List[_PendingSentence] = []
        self._tasks: Set["asyncio.Task[SynthesisResult | None]"] = set()
        self._queue: "asyncio.Queue[Optional[_PendingSentence]]" = asyncio.Queue()
        self._closed = False

    def feed(self, text: str) -> None:
        if self._closed:
            return

        *complete, self._buf = _SENTENCE_SPLIT.split(self._buf + text)
        for sentence in complete:
            self._submit(sentence)

    def break_sentence(self) -> None:
        """目前 buffer 視為完整一句送出，不與後續文字接在一起"""
        if self._closed:
            return
        self._submit(self._buf)
        self._buf = ""

    def end_turn(self) -> None:
        self.break_sentence()
        self._turn = []

    def reset(self) -> None:
        """丟棄本輪：buffer 與尚未送出的句子；已 yield 的結果收不回"""
        self._buf = ""
        for pending in self._turn:
            pending.dropped = True
            pending.task.cancel()
        self._turn = []

    def close(self) -> None:
        """不再有新文字；剩餘 buffer 視為最後一句，results() 送完後結束"""
        if self._closed:
            return
        self.end_turn()
        self._closed = True
        self._queue.put_nowait(None)

    async def aclose(self) -> None:
        """取消所有尚未完成的合成"""
        self._closed = True
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def results(self) -> AsyncIterator["SynthesisResult"]:
        while True:
            pending = await self._queue.get()
            if pending is None:
                return
            # 用 wait 而非直接 await：該句被 reset 取消時不會把 CancelledError 拋給呼叫端
            await asyncio.wait([pending.task])
            if pending.dropped or pending.task.cancelled():
                continue
            exc = pending.task.exception()
            if exc is not None:
                logger.warning("VoiceService: failed to synthesize sentence {!r}: {}", pending.sentence[:80], exc)
                continue
            result = pending.task.result()
            if result is not None:
                yield result

    def _submit(self, sentence: str) -> None:
        sentence = sentence.strip()
        if not sentence:
            return
        task = asyncio.create_task(self._run(sentence))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        pending = _PendingSentence(sentence, task)
        self._turn.append(pending)
        self._queue.put_nowait(pending)

    async def _run(self, sentence: str) -> "SynthesisResult | None":
        async with self._sem:
            return await self._synthesize(sentence)


__all__ = ["VoiceService", "SynthesisResult", "SentenceStream"]
