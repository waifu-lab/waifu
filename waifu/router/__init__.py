from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

from .health import router as health_router

if TYPE_CHECKING:
    from waifu.gateway.adapters.http import HTTPAdapter
    from waifu.gateway.adapters.waifu_node import WaifuNodeAdapter
    from waifu.gateway.adapters.websocket import WebSocketAdapter
    from waifu.service.character import CharacterService
    from waifu.service.config import AppConfigService
    from waifu.service.mcp import MCPService
    from waifu.service.plugin import PluginService


def include_routers(
    app: FastAPI,
    *,
    ws_adapter: "WebSocketAdapter | None" = None,
    http_adapter: "HTTPAdapter | None" = None,
    waifu_node_adapter: "WaifuNodeAdapter | None" = None,
    plugin_service: "PluginService | None" = None,
    mcp_service: "MCPService | None" = None,
    config_service: "AppConfigService | None" = None,
    character_service: "CharacterService | None" = None,
) -> None:
    from .chat import make_chat_router
    from .plugin import make_plugin_router
    from .waifu_node import make_waifu_node_router
    from .ws import make_ws_router

    app.include_router(health_router)

    if ws_adapter is not None:
        app.include_router(make_ws_router(ws_adapter))

    if http_adapter is not None:
        app.include_router(make_chat_router(http_adapter))

    if waifu_node_adapter is not None:
        app.include_router(make_waifu_node_router(waifu_node_adapter))

    if plugin_service is not None:
        app.include_router(make_plugin_router(plugin_service))

    if mcp_service is not None:
        from .mcp import make_mcp_router

        app.include_router(make_mcp_router(mcp_service))

    if config_service is not None:
        from .config import make_config_router

        app.include_router(make_config_router(config_service))

    if character_service is not None:
        from .character import make_character_router

        app.include_router(make_character_router(character_service))


__all__ = ["include_routers"]
