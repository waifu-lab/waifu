import base64
import logging
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional

from waifu_types import BaseGatewayAdapter, ConversationMode, IncomingRequest, OutgoingResponse, Sender

if TYPE_CHECKING:
    from fastapi import FastAPI
    from fastapi.websockets import WebSocket

    from waifu.gateway.core import GatewayCore
    from waifu.voice.service import VoiceService

logger = logging.getLogger(__name__)


class WebSocketAdapter(BaseGatewayAdapter):
    """
    FastAPI WebSocket Adapter — SESSION 模式

    支援兩種輸入訊息：
      { type: "chat",  conversation_id?, request_id?, content }
      { type: "voice", conversation_id?, request_id?, audio: "<b64>", format: "webm" }

    voice 訊息會先呼叫 VoiceService.transcribe() 轉為文字，再以正常 chat 流程處理
    若未設定 voice_service，voice 訊息會被靜默忽略

    用法：
        ws_adapter = WebSocketAdapter(voice_service=voice_svc)
        ws_adapter.mount(app, path="/ws")
        waifu.mount(ws_adapter)
    """

    name = "websocket"

    def __init__(self, voice_service: Optional["VoiceService"] = None) -> None:
        self._core: Optional["GatewayCore"] = None
        self._voice: Optional["VoiceService"] = voice_service

    async def start(self, core: "GatewayCore") -> None:
        self._core = core

    async def send(self, response: OutgoingResponse) -> None:
        # WebSocket 傳送由每個連線的 reply_fn 負責，此方法為 fallback
        pass

    def mount(self, app: "FastAPI", path: str = "/ws") -> None:
        """將 WebSocket endpoint 掛載到 FastAPI app"""
        from fastapi import WebSocket, WebSocketDisconnect

        adapter = self

        @app.websocket(path)
        async def ws_endpoint(websocket: WebSocket) -> None:
            await adapter.handle(websocket)

    async def handle(self, websocket: "WebSocket") -> None:
        """處理單一 WebSocket 連線的完整生命週期"""
        await websocket.accept()
        session_token = str(uuid.uuid4())

        try:
            while True:
                data: Dict[str, Any] = await websocket.receive_json()

                msg_type: str = data.get("type", "")
                if msg_type not in ("chat", "voice"):
                    continue

                request_id: str = data.get("request_id", str(uuid.uuid4()))
                raw_cid: str = data.get("conversation_id") or session_token
                conversation_id = f"ws:{raw_cid}" if not raw_cid.startswith("ws:") else raw_cid

                # ── 語音輸入：STT → 轉為文字 ──────────────────────────────
                if msg_type == "voice":
                    if self._voice is None or not self._voice.has_stt:
                        logger.debug("voice message received but STT not configured, ignored")
                        continue
                    try:
                        audio_b64: str = data.get("audio", "")
                        audio_format: str = data.get("format", "webm")
                        audio_bytes = base64.b64decode(audio_b64)
                        content = await self._voice.transcribe(audio_bytes, format=audio_format)
                        if not content.strip():
                            continue
                    except Exception:
                        logger.exception("STT transcription failed for session %s", session_token)
                        continue
                else:
                    content = data.get("content", "")

                reply_fn = _make_ws_reply_fn(websocket, request_id)

                request = IncomingRequest(
                    request_id=request_id,
                    conversation_id=conversation_id,
                    mode=ConversationMode.session,
                    sender=Sender(user_id=f"ws:{session_token}", display_name="User"),
                    source=self.name,
                    content=content,
                    live2d=bool(data.get("live2d", False)),
                    reply_fn=reply_fn,
                )

                if self._core is not None:
                    await self._core.dispatch(request)

        except Exception:
            logger.debug("WebSocket connection closed: %s", session_token)


def _make_ws_reply_fn(websocket: "WebSocket", request_id: str):
    """建立綁定到此 WebSocket 連線的 reply_fn

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
