import json
from typing import List, Optional

from waifu.store.models import MCPServer


class MCPRepository:
    def create(self, name: str, type: str, command, url, config: dict) -> MCPServer:
        return MCPServer.create(
            name=name,
            type=type,
            command=json.dumps(command) if command else None,
            url=url,
            config_json=json.dumps(config),
        )

    def delete(self, name: str) -> None:
        MCPServer.delete().where(MCPServer.name == name).execute()

    def set_enabled(self, name: str, enabled: bool) -> None:
        MCPServer.update(enabled=enabled).where(MCPServer.name == name).execute()

    def get(self, name: str) -> Optional[MCPServer]:
        return MCPServer.get_or_none(MCPServer.name == name)

    def list_enabled(self) -> List[MCPServer]:
        return list(MCPServer.select().where(MCPServer.enabled == True))  # noqa: E712

    def list_all(self) -> List[MCPServer]:
        return list(MCPServer.select())
