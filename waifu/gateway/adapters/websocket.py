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

    def __init__(
        self,
        voice_service: Optional["VoiceService"] = None,
        character_name: str = "Assistant",
    ) -> None:
        self._core: Optional["GatewayCore"] = None
        self._voice: Optional["VoiceService"] = voice_service
        self._heartbeat: Optional["HeartbeatManager"] = None
        self._connections: Dict[str, "WebSocket"] = {}  # session_token → websocket
        self._character_name = character_name

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
                    await self._handle_live2dsync(websocket, session_token, data)
                elif msg_type == "event":
                    self._handle_heartbeat_event(websocket, session_token, data)
                elif msg_type in ("chat", "voice"):
                    await self._handle_chat(websocket, session_token, data, msg_type)

        except Exception:
            logger.debug("WebSocket connection closed: {}", session_token)
        finally:
            self._connections.pop(session_token, None)

    async def _handle_live2dsync(
        self, websocket: "WebSocket", session_token: str, data: Dict[str, Any]
    ) -> None:
        expressions: list = data.get("expressions", [])
        if self._core is not None:
            session = self._core.session_manager.get_or_create(session_token)
            session.metadata["live2d_expressions"] = expressions
            logger.debug("live2dsync: stored {} expressions for session {}", len(expressions), session_token)
        await websocket.send_json({"type": "live2dsync_ack", "count": len(expressions)})

    def _handle_heartbeat_event(
        self, websocket: "WebSocket", session_token: str, data: Dict[str, Any]
    ) -> None:
        if self._heartbeat is None:
            return
        event_name: str = data.get("name", "")
        event_data: dict = data.get("data", {})
        if self._core is not None:
            ws_session = self._core.session_manager.get_or_create(session_token)
            exprs = ws_session.metadata.get("live2d_expressions")
            if exprs:
                event_data = {**event_data, "_live2d_expressions": exprs}
        reply_fn = _make_heartbeat_reply_fn(websocket, self._character_name)
        asyncio.create_task(
            self._heartbeat.dispatch(event_name, event_data, session_token, session_token, reply_fn)
        )

    async def _handle_chat(
        self, websocket: "WebSocket", session_token: str, data: Dict[str, Any], msg_type: str
    ) -> None:
        request_id: str = data.get("request_id", str(uuid.uuid4()))
        conversation_id: str = data.get("conversation_id") or session_token

        content = await self._resolve_content(websocket, session_token, request_id, data, msg_type)
        if content is None:
            return

        attachments = _parse_attachments(data)
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

    async def _resolve_content(
        self,
        websocket: "WebSocket",
        session_token: str,
        request_id: str,
        data: Dict[str, Any],
        msg_type: str,
    ) -> Optional[str]:
        if msg_type != "voice":
            return data.get("content", "")
        if self._voice is None or not self._voice.has_stt:
            logger.debug("voice message received but STT not configured, ignored")
            return None
        try:
            audio_bytes = base64.b64decode(data.get("audio", ""))
            content = await self._voice.transcribe(audio_bytes, format=data.get("format", "webm"))
            logger.debug("STT transcription result: {!r}", content)
            if not content.strip():
                logger.debug("STT returned empty content, ignoring")
                return None
            await websocket.send_json({"type": "transcript", "request_id": request_id, "content": content})
            return content
        except Exception:
            logger.exception("STT transcription failed for session {}", session_token)
            return None


def _parse_attachments(data: Dict[str, Any]) -> list[Attachment]:
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
    return attachments


def _make_heartbeat_reply_fn(websocket: "WebSocket", name: str = "Assistant"):
    async def reply_fn(content: str | None = None, *, event: dict | None = None, **_) -> None:
        if event is not None:
            await websocket.send_json({"type": "event", **event})
        elif content is not None:
            await websocket.send_json({"type": "event", "event": "dialogue", "data": {"name": name, "text": content}})

    return reply_fn


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
