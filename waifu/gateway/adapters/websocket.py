import asyncio
import base64
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional

from waifu.logger import logger
from waifu_types import Attachment, BaseGatewayAdapter, ConversationMode, IncomingRequest, OutgoingResponse, Sender

if TYPE_CHECKING:
    from fastapi import FastAPI
    from fastapi.websockets import WebSocket

    from waifu.gateway.core import GatewayCore
    from waifu.heartbeat.manager import HeartbeatManager
    from waifu.voice.service import VoiceService


class WebSocketAdapter(BaseGatewayAdapter):
    """
    FastAPI WebSocket Adapter — SESSION 模式

    支援以下輸入訊息：
      { type: "chat",  conversation_id?, request_id?, content, attachments?: [...] }
      { type: "voice", conversation_id?, request_id?, audio: "<b64>", format: "webm" }
      { type: "event", name: "<event_name>", data: {...} }   ← heartbeat 觸發

    voice 訊息會先呼叫 VoiceService.transcribe() 轉為文字，再以正常 chat 流程處理。
    event 訊息路由到 HeartbeatManager，由各 handler 決定如何回應。
    """

    name = "websocket"

    def __init__(self, voice_service: Optional["VoiceService"] = None) -> None:
        self._core: Optional["GatewayCore"] = None
        self._voice: Optional["VoiceService"] = voice_service
        self._heartbeat: Optional["HeartbeatManager"] = None
        self._connections: Dict[str, "WebSocket"] = {}  # session_token → websocket

    def set_heartbeat_manager(self, manager: "HeartbeatManager") -> None:
        self._heartbeat = manager

    async def start(self, core: "GatewayCore") -> None:
        self._core = core

    async def send(self, response: OutgoingResponse) -> None:
        pass

    def mount(self, app: "FastAPI", path: str = "/ws") -> None:
        adapter = self

        @app.websocket(path)
        async def ws_endpoint(websocket: "WebSocket") -> None:
            await adapter.handle(websocket)

    async def handle(self, websocket: "WebSocket") -> None:
        await websocket.accept()
        session_token = str(uuid.uuid4())
        self._connections[session_token] = websocket

        capabilities = self._core.capabilities if self._core is not None else {}
        await websocket.send_json({"type": "connected", "session_token": session_token, **capabilities})

        try:
            while True:
                data: Dict[str, Any] = await websocket.receive_json()
                msg_type: str = data.get("type", "")

                if msg_type == "live2dsync":
                    expressions: list = data.get("expressions", [])
                    if self._core is not None:
                        session = self._core.session_manager.get_or_create(session_token)
                        session.metadata["live2d_expressions"] = expressions
                        logger.debug(
                            "live2dsync: stored {} expressions for session {}", len(expressions), session_token
                        )
                    await websocket.send_json({"type": "live2dsync_ack", "count": len(expressions)})
                    continue

                if msg_type == "event":
                    if self._heartbeat is not None:
                        event_name: str = data.get("name", "")
                        event_data: dict = data.get("data", {})
                        push_fn = _make_ws_push_fn(websocket)
                        asyncio.create_task(
                            self._heartbeat.dispatch(event_name, event_data, session_token, session_token, push_fn)
                        )
                    continue

                if msg_type not in ("chat", "voice"):
                    continue

                request_id: str = data.get("request_id", str(uuid.uuid4()))
                conversation_id: str = data.get("conversation_id") or session_token

                if msg_type == "voice":
                    if self._voice is None or not self._voice.has_stt:
                        logger.debug("voice message received but STT not configured, ignored")
                        continue
                    try:
                        audio_b64: str = data.get("audio", "")
                        audio_format: str = data.get("format", "webm")
                        audio_bytes = base64.b64decode(audio_b64)
                        content = await self._voice.transcribe(audio_bytes, format=audio_format)
                        logger.debug("STT transcription result: {!r}", content)
                        if not content.strip():
                            logger.debug("STT returned empty content, ignoring")
                            continue
                        await websocket.send_json({"type": "transcript", "request_id": request_id, "content": content})
                    except Exception:
                        logger.exception("STT transcription failed for session {}", session_token)
                        continue
                else:
                    content = data.get("content", "")

                attachments: list[Attachment] = []
                for raw in data.get("attachments", []):
                    try:
                        raw_data = base64.b64decode(raw.get("data", "")) if raw.get("data") else b""
                        attachments.append(
                            Attachment(
                                filename=raw.get("filename", ""),
                                content_type=raw.get("content_type", "application/octet-stream"),
                                data=raw_data,
                                url=raw.get("url") or None,
                            )
                        )
                    except Exception:
                        logger.warning("Failed to parse attachment in WebSocket message, skipping")

                reply_fn = _make_ws_reply_fn(websocket, request_id)

                request = IncomingRequest(
                    request_id=request_id,
                    conversation_id=conversation_id,
                    mode=ConversationMode.session,
                    sender=Sender(user_id=f"ws:{session_token}", display_name="User"),
                    source=self.name,
                    content=content,
                    attachments=attachments,
                    live2d=bool(data.get("live2d", False)),
                    need_lipsync=bool(data.get("need_lipsync", False)),
                    reply_fn=reply_fn,
                )

                if self._core is not None:
                    await self._core.dispatch(request)

        except Exception:
            logger.debug("WebSocket connection closed: {}", session_token)
        finally:
            self._connections.pop(session_token, None)


def _make_ws_push_fn(websocket: "WebSocket"):
    """建立 heartbeat 推送函式，以 type: proactive 送出。"""

    async def push_fn(content: str) -> None:
        await websocket.send_json({"type": "proactive", "content": content})

    return push_fn


def _make_ws_reply_fn(websocket: "WebSocket", request_id: str):
    async def reply_fn(
        response: Optional[OutgoingResponse] = None,
        *,
        chunk: Optional[str] = None,
        event: Optional[dict] = None,
    ) -> None:
        if chunk is not None:
            await websocket.send_json({"type": "chunk", "request_id": request_id, "content": chunk})
        elif event is not None:
            await websocket.send_json({"type": "event", **event})
        elif response is not None:
            for ev in response.events:
                await websocket.send_json({"type": "event", **ev})
            await websocket.send_json({"type": "done", "request_id": response.request_id, "content": response.content})

    return reply_fn
