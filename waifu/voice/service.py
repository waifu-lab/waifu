import asyncio
import base64
import re
from typing import TYPE_CHECKING, AsyncIterator, Callable, Dict, List, Optional, Protocol

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


def _split_sentences(text: str) -> List[str]:
    parts = _SENTENCE_SPLIT.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


class VoiceService:
    @classmethod
    def from_config(cls, config: "VoiceConfig") -> "VoiceService":
        return cls(
            stt=config.stt.build() if config.stt else None,
            tts=config.tts.build() if config.tts else None,
            lipsync_fps=config.lipsync_fps,
            tts_timeout_retries=config.tts.timeout_retries if config.tts else 0,
            tts_retry_backoff_s=config.tts.retry_backoff_s if config.tts else 0.0,
            translator=config.translation.build() if config.translation else None,
        )

    def __init__(
        self,
        stt: Optional["ProviderSTT"] = None,
        tts: Optional[TTSProvider] = None,
        lipsync_fps: int = 20,
        tts_timeout_retries: int = 2,
        tts_retry_backoff_s: float = 0.5,
        translator: Optional["DeepLTranslator"] = None,
    ) -> None:
        self._stt = stt
        self._tts = tts
        self._lipsync_fps = lipsync_fps
        self._tts_timeout_retries = max(0, tts_timeout_retries)
        self._tts_retry_backoff_s = max(0.0, tts_retry_backoff_s)
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

    # TODO: 尚未使用 synthesize_stream；可改為合成下一句的同時播放上一句
    async def synthesize_sentences(
        self,
        text: str,
        need_lipsync: bool = False,
        clean: Optional[Callable[[str], str]] = None,
    ) -> AsyncIterator["SynthesisResult"]:

        if self._tts is None:
            raise RuntimeError("VoiceService: TTS provider not configured")

        sentences = _split_sentences(text)
        if not sentences:
            return

        fmt = self._tts.response_format

        async def _one(sentence: str) -> "SynthesisResult | None":
            spoken = (clean(sentence) if clean is not None else sentence).strip()
            if not spoken:
                return None
            tts_text = await self._translate(spoken)
            audio_bytes = await self._synthesize_with_retry(sentence, tts_text)
            visemes = build_lipsync_events(spoken, frames=self._lipsync_fps) if need_lipsync else []
            return SynthesisResult(
                audio_bytes=audio_bytes,
                format=fmt,
                lipsync_events=visemes,
                sentence=sentence,
            )

        for sentence in sentences:
            try:
                result = await _one(sentence)
            except Exception as exc:
                logger.warning("VoiceService: failed to synthesize sentence {!r}: {}", sentence[:80], exc)
                continue

            if result is not None:
                yield result

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


__all__ = ["VoiceService", "SynthesisResult"]
