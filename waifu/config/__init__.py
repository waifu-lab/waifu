from typing import Literal, Optional

from pydantic import BaseModel


class GatewayConfig(BaseModel):
    host: str = "localhost"
    port: int = 8765
    session_ttl: int = 3600
    lane_max_queue: int = 10


class ContextConfig(BaseModel):
    system_prompt_template: str = "You are a helpful assistant."
    max_history_messages: int = 20
    history_strategy: Literal["sliding", "summary", "full"] = "sliding"
    soul_content: Optional[str] = None  # soul.md content
    context_token_budget: Optional[int] = None  # None = 不限制；粗估 chars/4
    compact_threshold: float = 0.85  # 超過 budget * threshold 時觸發額外截斷


class ProviderConfig(BaseModel):
    provider: str
    api_key: str
    base_url: Optional[str] = None  # expect "custom" provider
    model: str
    temperature: float = 0.7
    max_tokens: Optional[int] = None


class STTConfig(BaseModel):
    """語音辨識設定（OpenAI Whisper compatible）"""

    api_key: str
    base_url: str = "https://api.openai.com/v1/audio/transcriptions"
    model: str = "whisper-1"
    language: Optional[str] = None  # None = 自動偵測；"zh"、"en" 等 BCP-47
    temperature: float = 0.0


class TTSConfig(BaseModel):
    """語音合成設定（OpenAI TTS compatible）"""

    api_key: str
    base_url: str = "https://api.openai.com/v1/audio/speech"
    model: str = "tts-1"
    voice: str = "nova"  # alloy / echo / fable / onyx / nova / shimmer
    response_format: str = "mp3"
    speed: float = 1.0


class VoiceConfig(BaseModel):
    """語音功能設定（STT + TTS，皆可選）"""

    stt: Optional[STTConfig] = None
    tts: Optional[TTSConfig] = None
    lipsync_fps: int = 20  # 口型 viseme 取樣幀率


# TODO: node_tokens: dict[str, str]
class WaifuNodeConfig(BaseModel):
    """Waifu-Node (本機電腦控制節點) 設定"""

    enabled: bool = True
    path: str = "/node"
    token: str = ""  # 空字串 = 不驗證
    invoke_timeout_ms: int = 10000
    ping_interval_s: int = 30


class WaifuConfig(BaseModel):
    gateway: GatewayConfig = GatewayConfig()
    context: ContextConfig = ContextConfig()
    provider: ProviderConfig
    utility_provider: Optional[ProviderConfig] = None

    voice: Optional[VoiceConfig] = None  # None = 語音功能停用
    node: Optional[WaifuNodeConfig] = None  # None = 停用 waifu-node
    character: Optional[str] = None  # character name
