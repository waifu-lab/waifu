import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from waifu_types import ConversationInfo, StoredMessage

if TYPE_CHECKING:
    from waifu.store.conversation import ConversationStore


def _to_info(row: Any) -> ConversationInfo:
    return ConversationInfo(
        id=str(row.id),
        title=str(row.title),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_message(row: Any) -> StoredMessage:
    try:
        parts = json.loads(row.content)
    except (TypeError, ValueError):
        parts = [{"type": "text", "text": str(row.content)}]
    if not isinstance(parts, list):
        parts = [{"type": "text", "text": str(parts)}]
    return StoredMessage(id=str(row.id), role=str(row.role), content=parts, created_at=row.created_at)


class ConversationServiceFacade:
    def __init__(self, store: "ConversationStore") -> None:
        self._store = store

    def get(self, id: str) -> Optional[ConversationInfo]:
        row = self._store.get(id)
        return _to_info(row) if row is not None else None

    def create(self, title: str) -> ConversationInfo:
        return _to_info(self._store.create(title))

    def list(self, limit: int = 20) -> List[ConversationInfo]:
        return [_to_info(row) for row in self._store.list(limit)]

    def search(self, query: str) -> List[ConversationInfo]:
        return [_to_info(row) for row in self._store.search(query)]

    def get_messages(self, conversation_id: str, limit: int = 100) -> List[StoredMessage]:
        return [_to_message(row) for row in self._store.get_messages(conversation_id, limit)]

    def add_message(self, conversation_id: str, role: str, parts: Union[List[Dict[str, Any]], str]) -> StoredMessage:
        return _to_message(self._store.add_message(conversation_id, role, parts))
