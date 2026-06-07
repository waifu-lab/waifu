from __future__ import annotations

import base64
import mimetypes
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from waifu_types.types import Attachment, ConversationMode, IncomingRequest, Sender, UserMessage

_SUPPORTED_FILE_TYPES = {
    "application/pdf",
    "text/plain",
    "text/html",
    "text/css",
    "text/javascript",
    "text/markdown",
    "application/json",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/msword",
    "text/csv",
    "text/xml",
    "application/xml",
}

# Only PDF is accepted as a binary file block by the OpenAI API.
# All other supported types are text-decodable and sent as text content.
_FILE_BLOCK_TYPES = {"application/pdf"}


def _to_data_url(att: Attachment) -> str:
    if att.url:
        return att.url
    return f"data:{att.content_type};base64,{base64.b64encode(att.data).decode()}"


class MessageParts:
    def __init__(self, content: str = "", attachments: Optional[List[Attachment]] = None) -> None:
        self.content: str = content
        self.attachments: List[Attachment] = attachments or []

    def __add__(self, other: "MessageParts") -> "MessageParts":
        sep = "\n" if self.content and other.content else ""
        return MessageParts(
            content=self.content + sep + other.content,
            attachments=self.attachments + other.attachments,
        )

    def __repr__(self) -> str:
        return f"MessageParts(content={self.content!r}, attachments=[{len(self.attachments)}])"

    def to_user_message(self) -> UserMessage:
        """Convert to a LLM-ready UserMessage with multimodal parts."""
        parts: List[Dict[str, Any]] = []
        if self.content:
            parts.append({"type": "text", "text": self.content})
        for att in self.attachments:
            if att.content_type.startswith("image/"):
                if not att.data and not att.url:
                    continue
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": _to_data_url(att), "detail": "auto"},
                })
            elif att.content_type in _SUPPORTED_FILE_TYPES:
                if not att.data and not att.url:
                    continue
                if att.content_type in _FILE_BLOCK_TYPES:
                    parts.append({
                        "type": "file",
                        "file": {"filename": att.filename, "file_data": _to_data_url(att)},
                    })
                elif att.data:
                    text_content = att.data.decode(errors="replace")
                    parts.append({
                        "type": "text",
                        "text": f"[{att.filename}]\n{text_content}",
                    })
        return UserMessage(content=parts)

    def as_request_kwargs(self) -> Dict[str, Any]:
        return {"content": self.content, "attachments": self.attachments}

    def to_request(
        self,
        *,
        conversation_id: Optional[str] = None,
        mode: ConversationMode = ConversationMode.session,
        sender: Optional[Sender] = None,
        source: str = "sdk",
        reply_fn: Optional[Callable] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> IncomingRequest:
        if reply_fn is None:
            async def _noop(**kwargs: Any) -> None:
                pass
            reply_fn = _noop

        return IncomingRequest(
            conversation_id=conversation_id or str(uuid.uuid4()),
            mode=mode,
            sender=sender or Sender(user_id="sdk:local", display_name="User"),
            source=source,
            content=self.content,
            attachments=self.attachments,
            metadata=metadata or {},
            reply_fn=reply_fn,
        )


def text(content: str) -> MessageParts:
    return MessageParts(content=content)


def image(
    url: str = "",
    *,
    data: bytes = b"",
    filename: str = "image.png",
    content_type: str = "image/png",
) -> MessageParts:
    if not url and not data:
        raise ValueError("image() requires either url= or data=")
    if content_type == "image/png" and not filename.lower().endswith(".png"):
        guessed, _ = mimetypes.guess_type(filename)
        if guessed and guessed.startswith("image/"):
            content_type = guessed
    att = Attachment(filename=filename, content_type=content_type, data=data, url=url or None)
    return MessageParts(attachments=[att])


def file(data: bytes, filename: str, content_type: str = "") -> MessageParts:
    if not content_type:
        guessed, _ = mimetypes.guess_type(filename)
        content_type = guessed or "application/octet-stream"
    return MessageParts(attachments=[Attachment(filename=filename, content_type=content_type, data=data)])


def from_path(path: str | Path, *, text_prefix: str = "") -> MessageParts:
    p = Path(path)
    raw = p.read_bytes()
    content_type, _ = mimetypes.guess_type(str(p))
    content_type = content_type or "application/octet-stream"
    if content_type.startswith("image/"):
        parts = image(data=raw, filename=p.name, content_type=content_type)
    else:
        parts = file(raw, p.name, content_type)
    return text(text_prefix) + parts if text_prefix else parts
