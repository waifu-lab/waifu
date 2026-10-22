from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

if TYPE_CHECKING:
    from hai.providers import ProviderSTT

    from waifu.hook.memory import MemoryStore
    from waifu.voice.service import TTSProvider
    from waifu.voice.translator import DeepLTranslator


class MemoryBackendConfig(BaseModel):
    """記憶後端共用設定；子類以 backend 欄位區分，並負責 build() 出 MemoryStore"""

    backend: str

    def build(self, *, character: Optional[str], max_history: int, memory_dir: Path) -> "Optional[MemoryStore]":
        """回傳 None 表示使用 MemoryHook 預設的 in-memory store（不跨重啟保存）"""
        raise NotImplementedError


class NoMemoryConfig(MemoryBackendConfig):
    """不使用外部記憶"""

    backend: Literal["none"] = "none"

    def build(self, *, character: Optional[str], max_history: int, memory_dir: Path) -> "Optional[MemoryStore]":  # noqa: ARG002
        return None


class FileMemoryConfig(MemoryBackendConfig):
    """以 markdown 檔保存記憶與關係（memory_dir）"""

    backend: Literal["file"] = "file"
    share_direct_memories: bool = True

    def build(self, *, character: Optional[str], max_history: int, memory_dir: Path) -> "Optional[MemoryStore]":
        from waifu.store import FileMemoryStore

        return FileMemoryStore(
            memory_dir=memory_dir,
            character_name=character,
            max_recent=max_history,
            share_direct_memories=self.share_direct_memories,
        )


class AutoMemoryConfig(FileMemoryConfig):
    """有設定角色時同 file，否則同 none"""

    backend: Literal["auto"] = "auto"  # type: ignore[assignment]

    def build(self, *, character: Optional[str], max_history: int, memory_dir: Path) -> "Optional[MemoryStore]":
        if not character:
            return None
        return super().build(character=character, max_history=max_history, memory_dir=memory_dir)


class HistoryTreeMemoryConfig(MemoryBackendConfig):
    """HistoryTree 服務（向量 / 圖記憶）"""

    backend: Literal["history_tree"] = "history_tree"
    base_url: str = "http://localhost:8000"
    timeout_s: float = 10.0
    top_k: int = 5
    rerank: bool = False
    query_graph: Literal["world", "self", "all"] = "world"
    ingest_graph: Literal["world", "self"] = "world"

    def build(self, *, character: Optional[str], max_history: int, memory_dir: Path) -> "Optional[MemoryStore]":  # noqa: ARG002
        from waifu.store import HistoryTreeStore

        return HistoryTreeStore(
            base_url=self.base_url,
            timeout_s=self.timeout_s,
            top_k=self.top_k,
            rerank=self.rerank,
            query_graph=self.query_graph,
            ingest_graph=self.ingest_graph,
            character_name=character,
        )


# 新增記憶後端：繼承 MemoryBackendConfig、實作 build()，並加入此 Union
MemoryConfig = Annotated[
    Union[AutoMemoryConfig, NoMemoryConfig, FileMemoryConfig, HistoryTreeMemoryConfig],
    Field(discriminator="backend"),
]


def _normalize_memory(data: Any) -> Any:
    """
    backend 省略時視為 auto；
    並轉換舊格式 backend + [memory.file] / [memory.history_tree]（DB 與 config.toml 同步後即寫回新格式）
    """
    if not isinstance(data, dict):
        return data
    data = dict(data)
    backend = data.setdefault("backend", "auto")
    legacy_file = data.pop("file", None)
    legacy_tree = data.pop("history_tree", None)
    section = legacy_tree if backend == "history_tree" else legacy_file if backend in ("auto", "file") else None
    if isinstance(section, dict):
        data = {**section, **data}
    return data


class GatewayConfig(BaseModel):
    host: str = "localhost"
    port: int = 8765
    session_ttl: int = 3600
    lane_max_queue: int = 10


class ContextConfig(BaseModel):
    builtin_prompt: bool = True  # False = 不使用內建的人設 / CLI 說明 prompt，只用 system_prompt_template 與角色卡
    system_prompt_template: str = ""
    max_history_messages: int = 20
    history_strategy: Literal["sliding", "summary", "full"] = "sliding"  # "summary" 尚未實作，行為同 "sliding"
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

    def build(self) -> "ProviderSTT":
        from hai.providers import ProviderSTT

        return ProviderSTT(
            name="waifu-stt",
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            language=self.language,
            temperature=self.temperature,
        )


class TTSBackendConfig(BaseModel):
    """TTS 後端共用設定；子類以 backend 欄位區分，並負責 build() 出 provider"""

    backend: str
    timeout_retries: int = 1  # 單句合成逾時的重試次數
    retry_backoff_s: float = 0.1
    max_concurrency: int = 2

    def build(self) -> "TTSProvider":
        raise NotImplementedError


class OpenAITTSConfig(TTSBackendConfig):
    """OpenAI TTS compatible"""

    backend: Literal["openai"] = "openai"
    api_key: str
    base_url: str = "https://api.openai.com/v1/audio/speech"
    model: str = "tts-1"
    voice: str = "nova"  # alloy / echo / fable / onyx / nova / shimmer
    response_format: str = "mp3"
    speed: float = 1.0

    def build(self) -> "TTSProvider":
        from hai.providers import OpenAITTS

        return OpenAITTS(
            name="waifu-tts",
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            voice=self.voice,
            response_format=self.response_format,
            speed=self.speed,
        )


class GPTSoVITSTTSConfig(TTSBackendConfig):
    """GPT-SoVITS local server"""

    backend: Literal["gptsovits"] = "gptsovits"
    base_url: str = "http://127.0.0.1:9880"
    ref_audio_path: str = ""
    prompt_text: str = ""
    prompt_lang: str = "zh"
    text_lang: str = "zh"
    text_split_method: str = "cut5"
    batch_size: int = 1
    speed_factor: float = 1.0
    streaming_mode: int = 0  # 0=停用; 1=最佳品質; 2=中; 3=最快
    top_k: int = 15
    top_p: float = 1.0
    temperature: float = 1.0
    timeout: float = 60.0

    def build(self) -> "TTSProvider":
        from hai.providers.gptsovits import GPTSoVITSTTS

        class _GPTSoVITSTTS(GPTSoVITSTTS):
            # GPT-SoVITS /tts always returns WAV; VoiceService reads response_format
            response_format: str = "wav"

        return _GPTSoVITSTTS(
            base_url=self.base_url,
            ref_audio_path=self.ref_audio_path,
            prompt_text=self.prompt_text,
            prompt_lang=self.prompt_lang,
            text_lang=self.text_lang,
            text_split_method=self.text_split_method,
            batch_size=self.batch_size,
            speed_factor=self.speed_factor,
            streaming_mode=self.streaming_mode,
            top_k=self.top_k,
            top_p=self.top_p,
            temperature=self.temperature,
            timeout=self.timeout,
        )


# 新增 TTS 後端：繼承 TTSBackendConfig、實作 build()，並加入此 Union
TTSConfig = Annotated[Union[OpenAITTSConfig, GPTSoVITSTTSConfig], Field(discriminator="backend")]


class DeepLConfig(BaseModel):
    """DeepL 翻譯設定（TTS 合成前自動翻譯）"""

    api_key: str
    target_lang: str = "JA"  # 目標語言，預設日文

    def build(self) -> "DeepLTranslator":
        from waifu.voice.translator import DeepLTranslator

        return DeepLTranslator(api_key=self.api_key, target_lang=self.target_lang)


class VoiceConfig(BaseModel):
    """語音功能設定（STT + TTS，皆可選）"""

    stt: Optional[STTConfig] = None
    tts: Optional[TTSConfig] = None  # [voice.tts] backend = "openai" | "gptsovits"（省略時為 openai）
    lipsync_fps: int = 20  # 口型 viseme 取樣幀率
    translation: Optional[DeepLConfig] = None  # 設定後 TTS 前自動翻譯

    @model_validator(mode="before")
    @classmethod
    def _normalize_tts(cls, data: Any) -> Any:
        """
        tts.backend 省略時視為 openai；
        並轉換舊格式 tts_backend + tts / gptsovits_tts（DB 與 config.toml 同步後即寫回新格式）
        """
        if not isinstance(data, dict):
            return data
        data = dict(data)
        backend = data.pop("tts_backend", None)
        legacy_gptsovits = data.pop("gptsovits_tts", None)
        tts = data.get("tts")
        if backend == "gptsovits" and isinstance(legacy_gptsovits, dict):
            data["tts"] = {**legacy_gptsovits, "backend": "gptsovits"}
        elif isinstance(tts, dict) and "backend" not in tts:
            data["tts"] = {**tts, "backend": backend or "openai"}
        return data


class HooksConfig(BaseModel):
    """內建 hook 開關"""

    emotion: bool = True  # 解析 [emotion:xxx] 並送出情緒事件（僅 live2d 請求）
    tts: bool = True  # 需同時設定 voice 的 TTS
    logging: bool = True
    rate_limit_rpm: Optional[int] = None  # 設定後啟用 per-conversation 限流


class HeartbeatEventConfig(BaseModel):
    """單一 heartbeat 事件的設定。"""

    event_name: str
    kind: Literal["llm", "greeting_pool"]
    prompt: Optional[str] = None  # kind=llm 時使用
    pool: Optional[List[str]] = None  # kind=greeting_pool 時使用


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
    memory: MemoryConfig = AutoMemoryConfig()  # [memory] backend = "auto" | "none" | "file" | "history_tree"
    hooks: HooksConfig = HooksConfig()
    heartbeat: Optional[List[HeartbeatEventConfig]] = None  # None = 使用內建預設事件
    provider: ProviderConfig
    utility_provider: Optional[ProviderConfig] = None

    voice: Optional[VoiceConfig] = None  # None = 語音功能停用
    node: Optional[WaifuNodeConfig] = None  # None = 停用 waifu-node
    character: Optional[str] = None  # character name

    @field_validator("memory", mode="before")
    @classmethod
    def _migrate_memory(cls, data: Any) -> Any:
        return _normalize_memory(data)
