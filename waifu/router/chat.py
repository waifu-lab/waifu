import base64
from typing import TYPE_CHECKING, List, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from waifu_types import Attachment

if TYPE_CHECKING:
    from waifu.gateway.adapters.http import HTTPAdapter


class ChatAttachment(BaseModel):
    """附件描述，data 與 url 二擇一。"""

    filename: str = ""
    content_type: str = "application/octet-stream"
    data: str = ""  # base64 編碼的檔案內容
    url: str = ""  # 遠端圖片 URL


class ChatRequest(BaseModel):
    conversation_id: str = "default"
    content: str
    user_id: str = "http:anonymous"
    display_name: str = "User"
    attachments: List[ChatAttachment] = []


def _parse_attachments(raw: List[ChatAttachment]) -> List[Attachment]:
    result = []
    for a in raw:
        data = base64.b64decode(a.data) if a.data else b""
        result.append(
            Attachment(
                filename=a.filename,
                content_type=a.content_type,
                data=data,
                url=a.url or None,
            )
        )
    return result


def make_chat_router(http_adapter: "HTTPAdapter") -> APIRouter:
    router = APIRouter(prefix="/chat", tags=["chat"])

    @router.post("/")
    async def chat(body: ChatRequest) -> StreamingResponse:
        attachments = _parse_attachments(body.attachments)
        return await http_adapter.handle(body, attachments=attachments)

    return router
