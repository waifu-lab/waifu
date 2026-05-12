import asyncio
import json
import uuid
from typing import TYPE_CHECKING, AsyncIterator, List, Optional

from fastapi.responses import StreamingResponse

from waifu_types import Attachment, BaseGatewayAdapter, ConversationMode, IncomingRequest, OutgoingResponse, Sender

if TYPE_CHECKING:
    from waifu.gateway.core import GatewayCore
    from waifu.router.chat import ChatRequest

from waifu.logger import logger


class HTTPAdapter(BaseGatewayAdapter):
    """
    FastAPI REST Adapter — SESSION / DIRECT 模式，支援 SSE streaming

    每個請求建立一個 asyncio.Queue，agent 透過 reply_fn 寫入 chunks，
    StreamingResponse 讀取 queue 逐字回傳
    """

    name = "http"

    def __init__(self) -> None:
        self._core: Optional["GatewayCore"] = None

    async def start(self, core: "GatewayCore") -> None:
        self._core = core

    async def send(self, response: OutgoingResponse) -> None:
        pass  # HTTP 傳送由 reply_fn / StreamingResponse 負責

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
            event: Optional[dict] = None,
        ) -> None:
            nonlocal chunk_sent
            if chunk is not None:
                chunk_sent = True
                await queue.put({"type": "chunk", "content": chunk})
            elif event is not None:
                await queue.put({"type": "event", **event})
            elif response is not None:
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

        asyncio.create_task(self._core.dispatch(request))

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
