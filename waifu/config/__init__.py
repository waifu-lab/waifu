from typing import Literal, Optional

from pydantic import BaseModel


class GatewayConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8765
    session_ttl: int = 3600
    lane_max_queue: int = 10


class ContextConfig(BaseModel):
    system_prompt_template: str = "You are a helpful assistant."
    max_history_messages: int = 20
    history_strategy: Literal["sliding", "summary", "full"] = "sliding"


class ProviderConfig(BaseModel):
    api_key: str
    base_url: str
    model: str
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    stream: bool = True


class STTConfig(BaseModel):
    """語音辨識設定（OpenAI Whisper compatible）"""
    api_key: str
    base_url: str = "https://api.openai.com/v1/audio/transcriptions"
    model: str = "whisper-1"
    language: Optional[str] = None   # None = 自動偵測；"zh"、"en" 等 BCP-47
    temperature: float = 0.0


class TTSConfig(BaseModel):
    """語音合成設定（OpenAI TTS compatible）"""
    api_key: str
    base_url: str = "https://api.openai.com/v1/audio/speech"
    model: str = "tts-1"
    voice: str = "nova"              # alloy / echo / fable / onyx / nova / shimmer
    response_format: str = "mp3"
    speed: float = 1.0


class VoiceConfig(BaseModel):
    """語音功能設定（STT + TTS，皆可選）"""
    stt: Optional[STTConfig] = None
    tts: Optional[TTSConfig] = None
    lipsync_fps: int = 20            # 口型 viseme 取樣幀率


class WaifuConfig(BaseModel):
    gateway: GatewayConfig = GatewayConfig()
    context: ContextConfig = ContextConfig()
    provider: ProviderConfig
    voice: Optional[VoiceConfig] = None   # None = 語音功能停用
