from typing import Any, Dict, List, Protocol, runtime_checkable

from waifu_types.types import BaseMessage


@runtime_checkable
class BaseSession(Protocol):
    conversation_id: str
    history: List[BaseMessage]
    metadata: Dict[str, Any]

    def touch(self) -> None: ...
    def add_message(self, message: BaseMessage) -> None: ...
    def add_messages(self, messages: List[BaseMessage]) -> None: ...
