from typing import Any, Dict, List, Protocol, runtime_checkable


@runtime_checkable
class BaseSession(Protocol):
    conversation_id: str
    history: List[Dict[str, Any]]
    metadata: Dict[str, Any]

    def touch(self) -> None: ...
    def add_message(self, message: Dict[str, Any]) -> None: ...
    def add_messages(self, messages: List[Dict[str, Any]]) -> None: ...
