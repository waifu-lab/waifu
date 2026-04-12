import json
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import httpx
from waifu_types import BaseMCPAdapter

from waifu import __version__

if TYPE_CHECKING:
    from hai.tool.toolcalling import Tool

logger = logging.getLogger(__name__)


class SSEMCPAdapter(BaseMCPAdapter):
    """
    透過 HTTP SSE 與 MCP Server 溝通

    用法：
        SSEMCPAdapter("http://localhost:8080/sse")
    """

    def __init__(self, url: str) -> None:
        self._url = url.rstrip("/")
        self._tools_cache: "List[Tool]" = []
        self._client: Optional[httpx.AsyncClient] = None
        self._req_id = 0

    async def connect(self) -> None:
        self._client = httpx.AsyncClient(timeout=30.0)
        await self._initialize()
        self._tools_cache = await self._fetch_tools()
        logger.info("SSEMCPAdapter connected: %s (%d tools)", self._url, len(self._tools_cache))

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def list_tools(self) -> "List[Tool]":
        return list(self._tools_cache)

    async def call_tool(self, name: str, args: Dict[str, Any]) -> str:
        result = await self._send("tools/call", {"name": name, "arguments": args})
        content = result.get("content", [])
        if isinstance(content, list):
            parts = [c.get("text", "") for c in content if c.get("type") == "text"]
            return "\n".join(parts)
        return str(content)

    async def _initialize(self) -> None:
        await self._send(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "waifu", "version": __version__},
            },
        )

    async def _fetch_tools(self) -> "List[Tool]":
        from hai.tool import Tool

        resp = await self._send("tools/list", {})
        tools = []
        for t in resp.get("tools", []):
            tools.append(
                Tool(
                    name=t["name"],
                    description=t.get("description", ""),
                    parameters=t.get("inputSchema", {"type": "object", "properties": {}}),
                    func=lambda n=t["name"], **kw: self.call_tool(n, kw),
                )
            )
        return tools

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    async def _send(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        assert self._client is not None
        payload = {"jsonrpc": "2.0", "id": self._next_id(), "method": method, "params": params}
        resp = await self._client.post(self._url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"MCP SSE error ({method}): {data['error']}")
        return data.get("result", {})
