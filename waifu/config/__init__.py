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


class WaifuConfig(BaseModel):
    gateway: GatewayConfig = GatewayConfig()
    context: ContextConfig = ContextConfig()
    provider: ProviderConfig
