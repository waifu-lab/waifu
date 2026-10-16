import inspect
import uuid
from enum import Enum
from typing import Any, Awaitable, Dict, List, Literal, Optional, Protocol, Set, Union, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from waifu_types.keys import Feature
from waifu_types.trace import BaseExecutionTrace

ContentPart = Dict[str, Any]
MessageContent = Union[str, List[ContentPart], None]


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
    content: MessageContent


class UserMessage(BaseMessage):
    role: Literal["user"] = "user"
    content: List[ContentPart]


class AssistantMessage(BaseMessage):
    role: Literal["assistant"] = "assistant"
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None


class ToolMessage(BaseMessage):
    role: Literal["tool"] = "tool"
    content: str
    tool_call_id: str


class SystemMessage(BaseMessage):
    role: Literal["system"] = "system"
    content: str


LLMMessage = Union[UserMessage, AssistantMessage, ToolMessage]


class GenericMessage(BaseMessage):
    """Fallback for unknown/custom message roles. Preserves all extra fields."""

    model_config = ConfigDict(extra="allow")

    content: MessageContent = None


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
    url: Optional[str] = None  # 遠端 URL（Discord/Telegram CDN），與 data 二擇一


class Event(BaseModel):
    """推送給前端的事件，wire format 為 {"event": ..., "data": {...}}"""

    event: str
    data: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def coerce(cls, value: "Event | Dict[str, Any]") -> "Event":
        return value if isinstance(value, Event) else cls.model_validate(value)


@runtime_checkable
class ReplyFn(Protocol):
    def __call__(
        self,
        response: "Optional[OutgoingResponse]" = None,
        *,
        chunk: Optional[str] = None,
        event: Optional[Event] = None,
    ) -> Optional[Awaitable[None]]: ...


async def _invoke_reply(fn: ReplyFn, *args: Any, **kwargs: Any) -> None:
    result = fn(*args, **kwargs)
    if inspect.isawaitable(result):
        await result


class IncomingRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str
    mode: ConversationMode
    sender: Sender
    source: str
    """ adapter 名稱（"websocket" / "discord" / ...）"""
    content: str
    attachments: List[Attachment] = []
    metadata: Dict[str, Any] = {}
    features: Set[str] = Field(default_factory=set)
    """前端能力旗標（見 waifu_types.keys.Feature），由各 hook 自行解讀"""
    platform_command: Optional[str] = None
    """由平台原生指令（Discord slash / Telegram command）觸發時為指令名稱"""
    reply_fn: ReplyFn

    @model_validator(mode="before")
    @classmethod
    def _legacy_feature_flags(cls, data: Any) -> Any:
        """相容舊參數 live2d= / need_lipsync=，轉為 features"""
        if not isinstance(data, dict) or ("live2d" not in data and "need_lipsync" not in data):
            return data
        data = dict(data)
        features: Set[str] = set(data.get("features") or ())
        if data.pop("live2d", False):
            features.add(Feature.LIVE2D)
        if data.pop("need_lipsync", False):
            features.add(Feature.LIPSYNC)
        data["features"] = features
        return data

    def has_feature(self, name: str) -> bool:
        return name in self.features

    async def reply_chunk(self, text: str) -> None:
        await _invoke_reply(self.reply_fn, chunk=text)

    async def reply_event(self, event: "Event | Dict[str, Any]") -> None:
        await _invoke_reply(self.reply_fn, event=Event.coerce(event))

    async def reply(self, response: "OutgoingResponse") -> None:
        await _invoke_reply(self.reply_fn, response)


class OutgoingResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    request_id: str
    conversation_id: str
    source: str
    content: str
    trace: Optional[BaseExecutionTrace] = None
    events: List[Event] = []
