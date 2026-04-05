from abc import ABC, abstractmethod
from typing import Any, Dict, Protocol, runtime_checkable


@runtime_checkable
class PluginContext(Protocol):
    """插件載入時取得的系統資源存取點（waifu 實作，waifu-types 定義介面）。"""

    config: Dict[str, Any]

    def register_hook(self, hook: Any) -> None:
        """向 HookRegistry 注冊 Hook。"""
        ...

    def register_tool(self, tool: Any) -> None:
        """向 PluginRegistry 注冊 Tool。"""
        ...

    def register_mcp(self, name: str, adapter: Any) -> None:
        """向 PluginRegistry 注冊 MCP Adapter。"""
        ...


class BasePlugin(ABC):
    name: str
    version: str = "0.1.0"
    description: str = ""

    @abstractmethod
    async def on_load(self, ctx: PluginContext) -> None:
        """初始化：連線外部服務、注冊 Hook/Tool/MCP。"""
        ...

    async def on_enable(self) -> None:
        """插件被啟用時呼叫。"""

    async def on_disable(self) -> None:
        """插件被停用時呼叫。"""

    async def on_unload(self) -> None:
        """插件被卸載時呼叫，負責清理資源。"""
