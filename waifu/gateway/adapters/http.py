import asyncio
import json
import uuid
from typing import TYPE_CHECKING, Any, AsyncIterator, List, Optional

from fastapi.responses import StreamingResponse

from waifu_types import (
    Attachment,
    BaseGatewayAdapter,
    ConversationMode,
    Event,
    GatewayProtocol,
    IncomingRequest,
    OutgoingResponse,
    Sender,
)

if TYPE_CHECKING:
    from waifu.router.chat import ChatRequest


class HTTPAdapter(BaseGatewayAdapter):
    name = "http"

    @classmethod
    def default_gateway_config(cls) -> dict[str, object]:
        return {"enabled": True}

    @classmethod
    def from_gateway_config(cls, _config: dict[str, object], **deps: object) -> "HTTPAdapter | None":
        del deps
        # Cannot disable
        return cls()

    def __init__(self) -> None:
        self._core: Optional[GatewayProtocol] = None

    def routers(self) -> List[Any]:
        from waifu.router.chat import make_chat_router

        return [make_chat_router(self)]

    async def start(self, core: GatewayProtocol) -> None:
        self._core = core

    async def handle(self, body: "ChatRequest", attachments: Optional[List[Attachment]] = None) -> StreamingResponse:
        if self._core is None:
            raise RuntimeError("HTTPAdapter not started")

        request_id = str(uuid.uuid4())
        conversation_id = body.conversation_id or str(uuid.uuid4())
        queue: asyncio.Queue[Optional[dict]] = asyncio.Queue()

        chunk_sent = False

        async def reply_fn(
            response: Optional[OutgoingResponse] = None,
            *,
            chunk: Optional[str] = None,
            event: Optional[Event] = None,
        ) -> None:
            nonlocal chunk_sent
            if chunk is not None:
                chunk_sent = True
                await queue.put({"type": "chunk", "content": chunk})
            elif event is not None:
                await queue.put({"type": "event", **event.model_dump()})
            elif response is not None:
                for ev in response.events:
                    await queue.put({"type": "event", **ev.model_dump()})
                if response.content and not chunk_sent:
                    await queue.put({"type": "chunk", "content": response.content})
                await queue.put(None)  # sentinel: stream end

        request = IncomingRequest(
            request_id=request_id,
            conversation_id=conversation_id,
            mode=ConversationMode.session,
            sender=Sender(user_id=body.user_id, display_name=body.display_name),
            source=self.name,
            content=body.content,
            attachments=attachments or [],
            reply_fn=reply_fn,
        )

        core = self._core

        async def _run() -> None:
            try:
                await core.dispatch_and_wait(request)
            except Exception:
                await queue.put({"type": "error", "content": "request failed"})
                await queue.put(None)

        asyncio.create_task(_run())

        return StreamingResponse(
            _sse_stream(queue),
            media_type="text/event-stream",
            headers={"X-Request-Id": request_id},
        )


async def _sse_stream(queue: asyncio.Queue) -> AsyncIterator[str]:
    """從 queue 讀取訊息（chunk / event），格式化為 SSE data lines"""
    while True:
        item = await queue.get()
        if item is None:
            yield "data: [DONE]\n\n"
            break
        payload = json.dumps(item, ensure_ascii=False)
        yield f"data: {payload}\n\n"
