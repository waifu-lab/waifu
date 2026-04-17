import json
from typing import List, Optional

from waifu.plugin import PluginManager
from waifu.plugin.builtin import MCPPlugin
from waifu.store.models import MCPServer
from waifu.store.repositories.mcp import MCPRepository


class MCPService:
    def __init__(self, repo: MCPRepository, plugin_manager: PluginManager) -> None:
        self._repo = repo
        self._pm = plugin_manager

    async def add(
        self,
        name: str,
        type: str,
        command=None,
        url: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> MCPServer:
        adapter = self._build_adapter(type, command, url)
        await self._pm.load(MCPPlugin(name, adapter))
        return self._repo.create(name, type, command, url, config or {})

    async def remove(self, name: str) -> None:
        await self._pm.unload(name)
        self._repo.delete(name)

    async def enable(self, name: str) -> None:
        row = self._repo.get(name)
        if row is None:
            raise KeyError(f"MCP server '{name}' not found")
        adapter = self._build_adapter(row.type, json.loads(row.command) if row.command else None, row.url)
        await self._pm.load(MCPPlugin(name, adapter))
        self._repo.set_enabled(name, True)

    async def disable(self, name: str) -> None:
        await self._pm.unload(name)
        self._repo.set_enabled(name, False)

    def list_all(self) -> List[MCPServer]:
        return self._repo.list_all()

    def _build_adapter(self, type: str, command, url: Optional[str]):
        from waifu.mcp import SSEMCPAdapter, StdioMCPAdapter

        return StdioMCPAdapter(command) if type == "stdio" else SSEMCPAdapter(url)
