# waifu-sdk: 純 re-export 層，讓第三方插件只需安裝此套件
# 實際定義都在 waifu-types（pydantic only，無重依賴）
from waifu_types import (
    Attachment,
    BaseGatewayAdapter,
    BaseHook,
    BaseMCPAdapter,
    BasePlugin,
    ConversationMode,
    HookContext,
    IncomingRequest,
    OutgoingResponse,
    PluginContext,
    Sender,
)

__all__ = [
    "BasePlugin",
    "PluginContext",
    "BaseGatewayAdapter",
    "BaseHook",
    "HookContext",
    "BaseMCPAdapter",
    "IncomingRequest",
    "OutgoingResponse",
    "Attachment",
    "ConversationMode",
    "Sender",
]
