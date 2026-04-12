import uuid
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from waifu_types.trace import BaseExecutionTrace


class ConversationMode(str, Enum):
    session = "session"  # WebSocket 1:1，以 session token 恢復歷史
    direct = "direct"  # 通訊軟體 1:1，以 user_id 持久化
    group = "group"  # 通訊軟體群組，以 room_id 持久化，多用戶


class Sender(BaseModel):
    user_id: str  # 全域唯一，e.g. "discord:user:123456"
    display_name: str  # 群組歷史標記用


class Attachment(BaseModel):
    filename: str
    content_type: str
    data: bytes = b""


class IncomingRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str
    mode: ConversationMode
    sender: Sender
    source: str  # adapter 名稱（"websocket" / "discord" / ...）
    content: str
    attachments: List[Attachment] = []
    metadata: Dict[str, Any] = {}
    live2d: bool = False  # True 時啟用情緒解析、TTS、lipsync 等 Live2D 功能
    # reply_fn(response: OutgoingResponse) 或 reply_fn(chunk=str) for streaming
    reply_fn: Callable


class OutgoingResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    request_id: str
    conversation_id: str
    source: str
    content: str
    chunks: List[str] = []
    trace: Optional[BaseExecutionTrace] = None
    events: List[Dict[str, Any]] = []  # Live2D emotion/action
    reply_fn: Callable
