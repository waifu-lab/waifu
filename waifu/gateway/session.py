import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Session:
    conversation_id: str
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    history: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        self.last_active = time.time()

    def add_message(self, message: Dict[str, Any]) -> None:
        self.history.append(message)
        self.touch()

    def add_messages(self, messages: List[Dict[str, Any]]) -> None:
        self.history.extend(messages)
        self.touch()


class SessionManager:
    """管理所有 conversation 的 Session，支援 TTL 自動過期"""

    def __init__(self, ttl: int = 3600):
        self._sessions: Dict[str, Session] = {}
        self._ttl = ttl

    def get_or_create(self, conversation_id: str) -> Session:
        self._evict_expired()
        if conversation_id not in self._sessions:
            self._sessions[conversation_id] = Session(conversation_id=conversation_id)
        return self._sessions[conversation_id]

    def get(self, conversation_id: str) -> Optional[Session]:
        return self._sessions.get(conversation_id)

    def delete(self, conversation_id: str) -> None:
        self._sessions.pop(conversation_id, None)

    def list_all(self) -> list:
        self._evict_expired()
        return list(self._sessions.values())

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [sid for sid, s in self._sessions.items() if now - s.last_active > self._ttl]
        for sid in expired:
            del self._sessions[sid]
