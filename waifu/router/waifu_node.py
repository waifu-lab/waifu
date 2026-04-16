from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket

if TYPE_CHECKING:
    from waifu.gateway.adapters.waifu_node import WaifuNodeAdapter

router = APIRouter(tags=["waifu-node"])


def make_waifu_node_router(adapter: "WaifuNodeAdapter", path: str = "/node") -> APIRouter:
    """建立並回傳綁定特定 WaifuNodeAdapter 的 router

    EX：
        node_adapter = WaifuNodeAdapter()
        app.include_router(make_waifu_node_router(node_adapter))
    """

    @router.websocket(path)
    async def waifu_node_endpoint(websocket: WebSocket) -> None:
        await adapter.handle(websocket)

    return router
