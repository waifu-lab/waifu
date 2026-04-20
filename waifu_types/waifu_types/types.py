import uuid
from enum import Enum
from typing import Any, Callable, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from waifu_types.trace import BaseExecutionTrace


# FROM shuvi/types.py
class ToolCallFunction(BaseModel):
    name: str
    arguments: str


class ToolCall(BaseModel):
    id: str
    type: Literal["function"] = "function"
    function: ToolCallFunction


class BaseMessage(BaseModel):
    role: str
    content: str


class UserMessage(BaseMessage):
    role: Literal["user"] = "user"


class AssistantMessage(BaseMessage):
    role: Literal["assistant"] = "assistant"
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None


class ToolMessage(BaseMessage):
    role: Literal["tool"] = "tool"
    tool_call_id: str


class SystemMessage(BaseMessage):
    role: Literal["system"] = "system"


LLMMessage = Union[UserMessage, AssistantMessage, ToolMessage]


class GenericMessage(BaseMessage):
    """Fallback for unknown/custom message roles. Preserves all extra fields."""

    model_config = ConfigDict(extra="allow")


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
