from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket

if TYPE_CHECKING:
    from waifu.gateway.adapters.websocket import WebSocketAdapter


def make_ws_router(ws_adapter: "WebSocketAdapter", path: str = "/ws") -> APIRouter:
    router = APIRouter(tags=["websocket"])

    @router.websocket(path)
    async def ws_endpoint(websocket: WebSocket) -> None:
        await ws_adapter.handle(websocket)

    return router
