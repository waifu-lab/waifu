from typing import Dict, List

from waifu_types import BaseMCPAdapter

from waifu.logger import logger
from waifu.plugin import PluginRegistry


class MCPManager:
    def __init__(self, plugin_registry: PluginRegistry) -> None:
        self._plugin_registry = plugin_registry
        self._adapters: Dict[str, BaseMCPAdapter] = {}
        self._tool_names: Dict[str, List[str]] = {}

    async def add(self, name: str, adapter: BaseMCPAdapter) -> None:
        if name in self._adapters:
            raise ValueError(f"MCP server '{name}' already registered")
        await adapter.connect()
        tools = await adapter.list_tools()
        for tool in tools:
            self._plugin_registry.add_tool(tool)
        self._adapters[name] = adapter
        self._tool_names[name] = [t.name for t in tools]
        self._plugin_registry.add_mcp(name, adapter)
        logger.info("MCP '{}' connected ({} tools)", name, len(tools))

    async def remove(self, name: str) -> None:
        adapter = self._adapters.pop(name, None)
        if adapter is None:
            return
        for tool_name in self._tool_names.pop(name, []):
            self._plugin_registry.remove_tool(tool_name)
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
