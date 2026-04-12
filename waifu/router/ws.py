from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket

if TYPE_CHECKING:
    from waifu.gateway.adapters.websocket import WebSocketAdapter

router = APIRouter(tags=["websocket"])


def make_ws_router(ws_adapter: "WebSocketAdapter") -> APIRouter:
    """建立並回傳綁定特定 WebSocketAdapter 的 router

    EX：
        ws_adapter = WebSocketAdapter()
        app.include_router(make_ws_router(ws_adapter))
    """

    @router.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        await ws_adapter.handle(websocket)

    return router
