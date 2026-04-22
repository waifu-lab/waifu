import base64
from typing import TYPE_CHECKING, Dict, List, Optional

from .lipsync import build_lipsync_events, estimate_duration_ms

if TYPE_CHECKING:
    from hai.providers.providers import ProviderSTT, ProviderTTS


class VoiceService:
    def __init__(
        self,
        stt: Optional["ProviderSTT"] = None,
        tts: Optional["ProviderTTS"] = None,
        lipsync_fps: int = 20,
    ) -> None:
        self._stt = stt
        self._tts = tts
        self._lipsync_fps = lipsync_fps

    @property
    def has_stt(self) -> bool:
        return self._stt is not None

    @property
    def has_tts(self) -> bool:
        return self._tts is not None

    async def transcribe(self, audio: bytes, format: str = "webm", language: Optional[str] = None) -> str:
        """
        語音轉文字
        """
        if self._stt is None:
            raise RuntimeError("VoiceService: STT provider not configured")
        return await self._stt.transcribe(audio, format=format, language=language)

    async def synthesize(self, text: str, need_lipsync: bool = False) -> "SynthesisResult":
        """
        文字轉語音；need_lipsync=True 時額外計算 viseme 事件

        :raises RuntimeError: 若未設定 TTS provider
        :return: SynthesisResult（audio_bytes, format, duration_ms, lipsync_events）
        """
        if self._tts is None:
            raise RuntimeError("VoiceService: TTS provider not configured")

        audio_bytes = await self._tts.synthesize(text)
        fmt = self._tts.response_format
        duration_ms = estimate_duration_ms(audio_bytes, fmt)
        visemes = build_lipsync_events(text, duration_ms, fps=self._lipsync_fps) if need_lipsync else []

        return SynthesisResult(
            audio_bytes=audio_bytes,
            format=fmt,
            duration_ms=duration_ms,
            lipsync_events=visemes,
        )

    def build_audio_events(self, result: "SynthesisResult") -> List[Dict]:
        """
        將 SynthesisResult 轉為 ctx.events 格式的事件列表

        一律送 audio 事件；lipsync_events 非空時才附加 lipsync 事件
        """
        audio_b64 = base64.b64encode(result.audio_bytes).decode()
        events: List[Dict] = [
            {
                "event": "audio",
                "data": {
                    "audio": audio_b64,
                    "format": result.format,
                    "duration_ms": result.duration_ms,
                },
            }
        ]
        if result.lipsync_events:
            events.append({"event": "lipsync", "data": {"visemes": result.lipsync_events}})
        return events


class SynthesisResult:
    """TTS 合成結果"""

    __slots__ = ("audio_bytes", "format", "duration_ms", "lipsync_events")

    def __init__(
        self,
        audio_bytes: bytes,
        format: str,
        duration_ms: int,
        lipsync_events: List[Dict],
    ) -> None:
        self.audio_bytes = audio_bytes
        self.format = format
        self.duration_ms = duration_ms
        self.lipsync_events = lipsync_events


__all__ = ["VoiceService", "SynthesisResult"]
