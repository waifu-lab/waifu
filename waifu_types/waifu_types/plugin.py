from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, Optional, Protocol, runtime_checkable

from waifu_types.command import CommandDefinition, CommandHandler
from waifu_types.services import ConversationService, SessionService, VoiceServiceProtocol
from waifu_types.tool import ToolLike

if TYPE_CHECKING:
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
        """註冊 Hook；插件停用 / 卸載時自動移除"""
        ...

    def register_tool(self, tool: ToolLike) -> None:
        """註冊 Tool（hai.tool.Tool 或 waifu_types.tool.FunctionTool）"""
        ...

    async def register_mcp(self, name: str, adapter: "BaseMCPAdapter") -> None:
        """連線 MCP Server 並註冊其工具；插件卸載時自動斷線"""
        ...

    async def register_adapter(self, adapter: "BaseGatewayAdapter") -> None:
        """掛載並啟動一個新的 Gateway Adapter
        若 gateway 已啟動，adapter 會立即 start；否則等 waifu.start() 時一併啟動
        """
        ...

    def register_adapter_type(self, adapter_type: type["BaseGatewayAdapter"]) -> None:
        """註冊可由 gateway config 驅動的 adapter 類型"""
        ...

    def register_command(self, definition: CommandDefinition, handler: CommandHandler) -> None:
        """註冊平台指令（/name args）；插件停用 / 卸載時自動移除"""
        ...


class BasePlugin(ABC):
    name: str
    version: str = "0.1.0"
    description: str = ""

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
