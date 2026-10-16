import asyncio
import base64
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from waifu.logger import logger
from waifu_types import (
    Attachment,
    BaseGatewayAdapter,
    ConversationMode,
    Event,
    Feature,
    GatewayProtocol,
    IncomingRequest,
    OutgoingResponse,
    ReplyFn,
    Sender,
    ServiceProvider,
    SessionMeta,
)

if TYPE_CHECKING:
    from fastapi.websockets import WebSocket

    from waifu.heartbeat.manager import HeartbeatManager
    from waifu.voice.service import VoiceService


class WebSocketAdapter(BaseGatewayAdapter):
    """
    FastAPI WebSocket Adapter — SESSION 模式

    支援以下輸入訊息：
      { type: "chat",  conversation_id?, request_id?, content, attachments?: [...], live2d?, need_lipsync? }
      { type: "voice", conversation_id?, request_id?, audio: "<b64>", format: "webm" }
      { type: "event", name: "<event_name>", data: {...} }   ← heartbeat 觸發
      { type: "live2dsync", expressions: [...] }

    voice 訊息會先呼叫 VoiceService.transcribe() 轉為文字，再以正常 chat 流程處理。
    event 訊息路由到 HeartbeatManager，由各 handler 決定如何回應。
    """

    name = "websocket"

    @classmethod
    def default_gateway_config(cls) -> dict[str, object]:
        return {"enabled": True}

    @classmethod
    def from_gateway_config(cls, _config: dict[str, object], **deps: object) -> "WebSocketAdapter | None":
        del deps
        # Cannot disable
        return cls()

    def __init__(
        self,
        voice_service: Optional["VoiceService"] = None,
        character_name: str = "Assistant",
        path: str = "/ws",
    ) -> None:
        self._core: Optional[GatewayProtocol] = None
        self._voice: Optional["VoiceService"] = voice_service
        self._heartbeat: Optional["HeartbeatManager"] = None
        self._connections: Dict[str, "WebSocket"] = {}  # session_token → websocket
        self._character_name = character_name
        self._path = path

    def on_mount(self, services: ServiceProvider) -> None:
        from waifu.heartbeat.manager import HeartbeatManager
        from waifu.voice.service import VoiceService

        self._heartbeat = services.get(HeartbeatManager)
        if self._voice is None:
            self._voice = services.get(VoiceService)

    def routers(self) -> List[Any]:
        from waifu.router.ws import make_ws_router

        return [make_ws_router(self, self._path)]

    async def start(self, core: GatewayProtocol) -> None:
        self._core = core

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

    async def _handle_live2dsync(self, websocket: "WebSocket", session_token: str, data: Dict[str, Any]) -> None:
        expressions: list = data.get("expressions", [])
        if self._core is not None:
            session = self._core.session_manager.get_or_create(session_token)
            session.metadata[SessionMeta.LIVE2D_EXPRESSIONS] = expressions
            logger.debug("live2dsync: stored {} expressions for session {}", len(expressions), session_token)
        await websocket.send_json({"type": "live2dsync_ack", "count": len(expressions)})

    def _handle_heartbeat_event(self, websocket: "WebSocket", session_token: str, data: Dict[str, Any]) -> None:
        if self._heartbeat is None:
            return
        event_name: str = data.get("name", "")
        event_data: dict = data.get("data", {})
        if self._core is not None:
            ws_session = self._core.session_manager.get_or_create(session_token)
            exprs = ws_session.metadata.get(SessionMeta.LIVE2D_EXPRESSIONS)
            if exprs:
                event_data = {**event_data, SessionMeta.LIVE2D_EXPRESSIONS: exprs}
        reply_fn = _make_heartbeat_reply_fn(websocket, self._character_name)
        asyncio.create_task(self._heartbeat.dispatch(event_name, event_data, session_token, session_token, reply_fn))

    async def _handle_chat(
        self, websocket: "WebSocket", session_token: str, data: Dict[str, Any], msg_type: str
    ) -> None:
        request_id: str = data.get("request_id", str(uuid.uuid4()))
        conversation_id: str = data.get("conversation_id") or session_token

        content = await self._resolve_content(websocket, session_token, request_id, data, msg_type)
        if content is None:
            return

        attachments = _parse_attachments(data)
        if attachments:
            logger.debug(
                "WebSocket attachments: {}",
                [
                    {"filename": a.filename, "content_type": a.content_type, "data_len": len(a.data), "url": a.url}
                    for a in attachments
                ],
            )

        request = IncomingRequest(
            request_id=request_id,
            conversation_id=conversation_id,
            mode=ConversationMode.session,
            sender=Sender(user_id=f"ws:{session_token}", display_name="User"),
            source=self.name,
            content=content,
            attachments=attachments,
            features=_parse_features(data),
            reply_fn=_make_ws_reply_fn(websocket, request_id),
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


def _parse_features(data: Dict[str, Any]) -> Set[str]:
    """wire format：features: [...]，或舊版布林欄位 live2d / need_lipsync"""
    features = {str(f) for f in data.get("features") or []}
    if data.get("live2d"):
        features.add(Feature.LIVE2D)
    if data.get("need_lipsync"):
        features.add(Feature.LIPSYNC)
    return features


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


def _event_frame(event: Event) -> Dict[str, Any]:
    return {"type": "event", **event.model_dump()}


def _make_heartbeat_reply_fn(websocket: "WebSocket", name: str = "Assistant") -> ReplyFn:
    """heartbeat 回覆以 dialogue 事件呈現，不送 chunk / done"""

    async def reply_fn(
        response: Optional[OutgoingResponse] = None,
        *,
        chunk: Optional[str] = None,
        event: Optional[Event] = None,
    ) -> None:
        del chunk
        if event is not None:
            await websocket.send_json(_event_frame(event))
        elif response is not None:
            for ev in response.events:
                await websocket.send_json(_event_frame(ev))
            if response.content:
                await websocket.send_json(
                    _event_frame(Event(event="dialogue", data={"name": name, "text": response.content}))
                )

    return reply_fn


def _make_ws_reply_fn(websocket: "WebSocket", request_id: str) -> ReplyFn:
    async def reply_fn(
        response: Optional[OutgoingResponse] = None,
        *,
        chunk: Optional[str] = None,
        event: Optional[Event] = None,
    ) -> None:
        if chunk is not None:
            await websocket.send_json({"type": "chunk", "request_id": request_id, "content": chunk})
        elif event is not None:
            await websocket.send_json(_event_frame(event))
        elif response is not None:
            for ev in response.events:
                await websocket.send_json(_event_frame(ev))
            await websocket.send_json({"type": "done", "request_id": response.request_id, "content": response.content})

    return reply_fn
