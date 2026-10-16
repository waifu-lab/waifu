from typing import TYPE_CHECKING, Dict, List

from waifu_types import BaseMCPAdapter

from waifu.logger import logger

if TYPE_CHECKING:
    from hai.tool import Tool

    from waifu.plugin import PluginRegistry


class MCPManager:
    def __init__(self, plugin_registry: "PluginRegistry") -> None:
        self._plugin_registry = plugin_registry
        self._adapters: Dict[str, BaseMCPAdapter] = {}
        self._tools: Dict[str, List["Tool"]] = {}

    async def add(self, name: str, adapter: BaseMCPAdapter) -> None:
        if name in self._adapters:
            raise ValueError(f"MCP server '{name}' already registered")
        await adapter.connect()
        tools = [self._plugin_registry.add_tool(t) for t in await adapter.list_tools()]
        self._adapters[name] = adapter
        self._tools[name] = tools
        self._plugin_registry.add_mcp(name, adapter)
        logger.info("MCP '{}' connected ({} tools)", name, len(tools))

    async def remove(self, name: str) -> None:
        adapter = self._adapters.pop(name, None)
        if adapter is None:
            return
        for tool in self._tools.pop(name, []):
            self._plugin_registry.remove_tool(tool.name, tool)
        self._plugin_registry.remove_mcp(name)
        try:
            await adapter.disconnect()
        except Exception:
            logger.exception("MCP '{}' disconnect failed", name)
        logger.info("MCP '{}' removed", name)

    def list(self) -> List[str]:
        return list(self._adapters.keys())

    def get(self, name: str) -> BaseMCPAdapter | None:
        return self._adapters.get(name)

    async def shutdown(self) -> None:
        for name in list(self._adapters.keys()):
            await self.remove(name)
