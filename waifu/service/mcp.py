import json
from typing import List, Optional, cast

from waifu.mcp import MCPManager, SSEMCPAdapter, StdioMCPAdapter
from waifu.store.models import MCPServer
from waifu.store.repositories.mcp import MCPRepository


class MCPService:
    def __init__(self, repo: MCPRepository, manager: MCPManager) -> None:
        self._repo = repo
        self._manager = manager

    async def add(
        self,
        name: str,
        type: str,
        command=None,
        url: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> MCPServer:
        adapter = self._build_adapter(type, command, url)
        await self._manager.add(name, adapter)
        return self._repo.create(name, type, command, url, config or {})

    async def remove(self, name: str) -> None:
        await self._manager.remove(name)
        self._repo.delete(name)

    async def enable(self, name: str) -> None:
        row = self._repo.get(name)
        if row is None:
            raise KeyError(f"MCP server '{name}' not found")
        row_command = cast(Optional[str], row.command)
        adapter = self._build_adapter(
            cast(str, row.type),
            json.loads(row_command) if row_command else None,
            cast(Optional[str], row.url),
        )
        await self._manager.add(name, adapter)
        self._repo.set_enabled(name, True)

    async def disable(self, name: str) -> None:
        await self._manager.remove(name)
        self._repo.set_enabled(name, False)

    def list_all(self) -> List[MCPServer]:
        return self._repo.list_all()

    def _build_adapter(self, type: str, command, url: Optional[str]):
        if type == "stdio":
            return StdioMCPAdapter(command)
        if url is None:
            raise ValueError("SSE MCP adapter requires a non-empty url")
        return SSEMCPAdapter(url)
