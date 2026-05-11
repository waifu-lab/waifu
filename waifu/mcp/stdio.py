import asyncio
import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from waifu_types import BaseMCPAdapter

from waifu import __version__

if TYPE_CHECKING:
    from hai.tool.toolcalling import Tool

from waifu.logger import logger


class StdioMCPAdapter(BaseMCPAdapter):
    """
    透過 stdio 與 MCP Server 溝通（JSON-RPC over stdin/stdout）

    用法：
        StdioMCPAdapter(["npx", "-y", "@modelcontextprotocol/server-filesystem", "."])
        StdioMCPAdapter(["python", "-m", "mcp_server_sqlite", "--db", "data.db"])
    """

    def __init__(self, cmd: List[str]) -> None:
        self._cmd = cmd
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._tools_cache: "List[Tool]" = []
        self._req_id = 0

    async def connect(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            *self._cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await self._initialize()
        self._tools_cache = await self._fetch_tools()
        logger.info("StdioMCPAdapter connected: {} ({} tools)", self._cmd[0], len(self._tools_cache))

    async def disconnect(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._proc.kill()
        self._proc = None

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
        await self._notify("notifications/initialized")

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
        assert self._proc and self._proc.stdin and self._proc.stdout
        req = json.dumps({"jsonrpc": "2.0", "id": self._next_id(), "method": method, "params": params})
        self._proc.stdin.write((req + "\n").encode())
        await self._proc.stdin.drain()

        line = await self._proc.stdout.readline()
        resp = json.loads(line)
        if "error" in resp:
            raise RuntimeError(f"MCP error ({method}): {resp['error']}")
        return resp.get("result", {})

    async def _notify(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        assert self._proc and self._proc.stdin
        req = json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}})
        self._proc.stdin.write((req + "\n").encode())
        await self._proc.stdin.drain()
