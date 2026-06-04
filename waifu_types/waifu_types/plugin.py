from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol, runtime_checkable

from waifu_types.services import ConversationService, SessionService, VoiceServiceProtocol

if TYPE_CHECKING:
    from hai.tool.toolcalling import Tool
    from waifu_types.adapter import BaseGatewayAdapter
    from waifu_types.hook import BaseHook
    from waifu_types.mcp import BaseMCPAdapter


@runtime_checkable
class PluginContext(Protocol):
    config: Dict[str, Any]
    gateway_config: Dict[str, Any]

    store: ConversationService
    """持久化對話歷史，可讀寫對話與訊息"""

    sessions: SessionService
    """進行中的 in-memory Session，可存取或注入 metadata"""

    voice: Optional[VoiceServiceProtocol]
    """TTS / STT 服務；未設定時為 None"""

    def register_hook(self, hook: "BaseHook") -> None:
        """向 HookRegistry 注冊 Hook"""
        ...

    def register_tool(self, tool: "Tool") -> None:
        """向 PluginRegistry 注冊 Tool"""
        ...

    def register_mcp(self, name: str, adapter: "BaseMCPAdapter") -> None:
        """向 PluginRegistry 注冊 MCP Adapter"""
        ...

    async def register_adapter(self, adapter: "BaseGatewayAdapter") -> None:
        """掛載並啟動一個新的 Gateway Adapter
        若 gateway 已啟動，adapter 會立即 start；否則等 waifu.start() 時一併啟動
        """
        ...

    def register_adapter_type(self, adapter_type: type["BaseGatewayAdapter"]) -> None: ...


class BasePlugin(ABC):
    name: str
    version: str = "0.1.0"
    description: str = ""
    registered_tools: List[str] = []
    registered_hooks: List[str] = []
    registered_mcps: List[str] = []
    registered_adapter_types: List[str] = []

    @abstractmethod
    async def on_load(self, ctx: PluginContext) -> None:
        """初始化：連線外部服務、注冊 Hook/Tool/MCP"""
        ...

    async def on_enable(self) -> None:  # noqa: B027
        """插件被啟用時呼叫"""

    async def on_disable(self) -> None:  # noqa: B027
        """插件被停用時呼叫"""

    async def on_unload(self) -> None:  # noqa: B027
        """插件被卸載時呼叫，負責清理資源"""
