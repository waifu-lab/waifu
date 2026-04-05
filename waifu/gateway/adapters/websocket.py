import logging
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional

from waifu_types import BaseGatewayAdapter, ConversationMode, IncomingRequest, OutgoingResponse, Sender

if TYPE_CHECKING:
    from waifu.gateway.core import GatewayCore

logger = logging.getLogger(__name__)


class WebSocketAdapter(BaseGatewayAdapter):
    """
    FastAPI WebSocket Adapter — SESSION 模式。

    用法：
        ws_adapter = WebSocketAdapter()
        ws_adapter.mount(app, path="/ws")   # 掛 FastAPI route
        waifu.mount(ws_adapter)
    """

    name = "websocket"

    def __init__(self) -> None:
        self._core: Optional["GatewayCore"] = None

    # ── BaseGatewayAdapter ────────────────────────────────────────────────

    async def start(self, core: "GatewayCore") -> None:
        self._core = core

    async def send(self, response: OutgoingResponse) -> None:
        # WebSocket 傳送由每個連線的 reply_fn 負責，此方法為 fallback
        pass

    # ── FastAPI 整合 ──────────────────────────────────────────────────────

    def mount(self, app: Any, path: str = "/ws") -> None:
        """將 WebSocket endpoint 掛載到 FastAPI app。"""
        from fastapi import WebSocket, WebSocketDisconnect

        adapter = self

        @app.websocket(path)
        async def ws_endpoint(websocket: WebSocket) -> None:
            await adapter.handle(websocket)

    async def handle(self, websocket: Any) -> None:
        """處理單一 WebSocket 連線的完整生命週期。"""
        await websocket.accept()
        session_token = str(uuid.uuid4())

        try:
            while True:
                data: Dict[str, Any] = await websocket.receive_json()

                if data.get("type") != "chat":
                    continue

                content: str = data.get("content", "")
                request_id: str = data.get("request_id", str(uuid.uuid4()))

                # 允許 client 帶 conversation_id 來跨重連恢復歷史
                raw_cid: str = data.get("conversation_id") or session_token
                conversation_id = f"ws:{raw_cid}" if not raw_cid.startswith("ws:") else raw_cid

                reply_fn = _make_ws_reply_fn(websocket, request_id)

                request = IncomingRequest(
                    request_id=request_id,
                    conversation_id=conversation_id,
                    mode=ConversationMode.session,
                    sender=Sender(user_id=f"ws:{session_token}", display_name="User"),
                    source=self.name,
                    content=content,
                    reply_fn=reply_fn,
                )

                if self._core is not None:
                    await self._core.dispatch(request)

        except Exception:
            logger.debug("WebSocket connection closed: %s", session_token)


def _make_ws_reply_fn(websocket: Any, request_id: str):
    """建立綁定到此 WebSocket 連線的 reply_fn。

    reply_fn 支援兩種呼叫方式：
      - reply_fn(response: OutgoingResponse)  → 送出 done 訊息
      - reply_fn(chunk="...")                 → 送出 chunk 訊息（streaming）
    """

    async def reply_fn(response: Optional[OutgoingResponse] = None, *, chunk: Optional[str] = None) -> None:
        if chunk is not None:
            await websocket.send_json({"type": "chunk", "request_id": request_id, "content": chunk})
        elif response is not None:
            for event in response.events:
                await websocket.send_json({"type": "event", **event})
            await websocket.send_json({"type": "done", "request_id": response.request_id, "content": response.content})

    return reply_fn
