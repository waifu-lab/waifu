import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from waifu.logger import logger
from waifu.mcp import MCPManager, SSEMCPAdapter, StdioMCPAdapter


class MCPService:
    """Manages MCP server lifecycle with mcp.json as the persistence layer."""

    def __init__(self, manager: MCPManager, config_path: Path) -> None:
        self._manager = manager
        self._config_path = config_path

    def _load(self) -> Dict[str, Any]:
        if not self._config_path.is_file():
            return {"servers": {}}
        return json.loads(self._config_path.read_text(encoding="utf-8"))

    @staticmethod
    def _resolve_command(entry: Dict[str, Any]) -> List[str]:
        """Support both {"command": [...]} and {"command": "exe", "args": [...]} formats."""
        cmd = entry.get("command")
        if isinstance(cmd, str):
            return [cmd] + list(entry.get("args", []))
        return list(cmd) if cmd else []

    @staticmethod
    def _entry_type(entry: Dict[str, Any]) -> str:
        """Treat both 'http' and 'sse' type fields as SSE; infer from url presence."""
        explicit = entry.get("type", "")
        if explicit in ("http", "sse") or "url" in entry:
            return "sse"
        return "stdio"

    def _save(self, data: Dict[str, Any]) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    async def load_all(self) -> None:
        """Connect all enabled servers on startup."""
        data = self._load()
        for name, entry in data.get("servers", {}).items():
            if not entry.get("enabled", True):
                continue
            type_ = self._entry_type(entry)
            try:
                adapter = self._build_adapter(
                    type_,
                    self._resolve_command(entry),
                    entry.get("url"),
                    entry.get("headers"),
                    entry.get("env"),
                )
                await self._manager.add(name, adapter)
            except Exception:
                logger.exception("Failed to load MCP server: {}", name)

    async def add(
        self,
        name: str,
        type: str,
        command: Optional[List[str]] = None,
        url: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        adapter = self._build_adapter(type, command, url, headers, env)
        await self._manager.add(name, adapter)

        data = self._load()
        servers = data.setdefault("servers", {})
        if type == "stdio":
            entry: Dict[str, Any] = {"command": command or []}
            if env:
                entry["env"] = env
        else:
            entry = {"url": url}
            if headers:
                entry["headers"] = headers
        servers[name] = entry
        self._save(data)
        return {"name": name, "type": type}

    async def remove(self, name: str) -> None:
        await self._manager.remove(name)
        data = self._load()
        if name not in data.get("servers", {}):
            raise KeyError(f"MCP server '{name}' not found")
        del data["servers"][name]
        self._save(data)

    async def enable(self, name: str) -> None:
        data = self._load()
        entry = data.get("servers", {}).get(name)
        if entry is None:
            raise KeyError(f"MCP server '{name}' not found")
        type_ = self._entry_type(entry)
        adapter = self._build_adapter(
            type_,
            self._resolve_command(entry),
            entry.get("url"),
            entry.get("headers"),
            entry.get("env"),
        )
        await self._manager.add(name, adapter)
        entry.pop("enabled", None)
        self._save(data)

    async def disable(self, name: str) -> None:
        await self._manager.remove(name)
        data = self._load()
        entry = data.get("servers", {}).get(name)
        if entry is None:
            raise KeyError(f"MCP server '{name}' not found")
        entry["enabled"] = False
        self._save(data)

    def list_all(self) -> List[Dict[str, Any]]:
        data = self._load()
        result = []
        for name, entry in data.get("servers", {}).items():
            type_ = self._entry_type(entry)
            if type_ == "sse":
                target: Any = entry.get("url", "")
            else:
                target = self._resolve_command(entry)
            result.append(
                {
                    "name": name,
                    "type": type_,
                    "enabled": entry.get("enabled", True),
                    "target": target,
                }
            )
        return result

    def _build_adapter(
        self,
        type: str,
        command: Any,
        url: Optional[str],
        headers: Optional[Dict[str, str]] = None,
        env: Optional[Dict[str, str]] = None,
    ):
        if type == "stdio":
            return StdioMCPAdapter(command, env=env)
        if url is None:
            raise ValueError("SSE MCP adapter requires a non-empty url")
        return SSEMCPAdapter(url, headers=headers)
