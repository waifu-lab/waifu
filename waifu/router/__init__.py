from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

from .health import router as health_router

if TYPE_CHECKING:
    from waifu.gateway.adapters.http import HTTPAdapter
    from waifu.gateway.adapters.websocket import WebSocketAdapter
    from waifu.plugin import PluginManager


def include_routers(
    app: FastAPI,
    *,
    ws_adapter: "WebSocketAdapter | None" = None,
    http_adapter: "HTTPAdapter | None" = None,
    plugin_manager: "PluginManager | None" = None,
) -> None:
    """將所有路由掛載到 FastAPI app
    """
    from .chat import make_chat_router
    from .plugin import make_plugin_router
    from .ws import make_ws_router

    app.include_router(health_router)

    if ws_adapter is not None:
        app.include_router(make_ws_router(ws_adapter))

    if http_adapter is not None:
        app.include_router(make_chat_router(http_adapter))

    if plugin_manager is not None:
        app.include_router(make_plugin_router(plugin_manager))


__all__ = ["include_routers"]
