from typing import TYPE_CHECKING

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

if TYPE_CHECKING:
    from waifu.gateway.adapters.http import HTTPAdapter

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    conversation_id: str = "default"
    content: str
    user_id: str = "http:anonymous"
    display_name: str = "User"


def make_chat_router(http_adapter: "HTTPAdapter") -> APIRouter:
    """建立並回傳綁定特定 HTTPAdapter 的 router"""

    @router.post("/")
    async def chat(body: ChatRequest) -> StreamingResponse:
        return await http_adapter.handle(body)

    return router
