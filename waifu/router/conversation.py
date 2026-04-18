import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from waifu.store.conversation import ConversationStore


def make_conversation_router(conversation_store: ConversationStore) -> APIRouter:
    router = APIRouter(prefix="/conversations", tags=["conversations"])

    @router.get("/")
    async def list_conversations(
        limit: int = 20, q: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if q:
            convs = conversation_store.search(q)
            if limit > 0:
                convs = convs[:limit]
        else:
            convs = conversation_store.list(limit)
        return [
            {
                "id": c.id,
                "title": c.title,
                "created_at": c.created_at.isoformat() + "Z",
                "updated_at": c.updated_at.isoformat() + "Z",
                "message_count": c.messages.count(),
            }
            for c in convs
        ]

    @router.get("/{id}")
    async def get_conversation(id: str) -> Dict[str, Any]:
        c = conversation_store.get(id)
        if c is None:
            raise HTTPException(status_code=404, detail=f"Conversation '{id}' not found")
        return {
            "id": c.id,
            "title": c.title,
            "created_at": c.created_at.isoformat() + "Z",
            "updated_at": c.updated_at.isoformat() + "Z",
            "message_count": c.messages.count(),
        }

    @router.get("/{id}/messages")
    async def get_messages(id: str, limit: int = 100) -> List[Dict[str, Any]]:
        c = conversation_store.get(id)
        if c is None:
            raise HTTPException(status_code=404, detail=f"Conversation '{id}' not found")
        msgs = conversation_store.get_messages(id, limit)
        result = []
        for m in msgs:
            try:
                parts = json.loads(m.content)
            except (json.JSONDecodeError, TypeError):
                parts = [{"type": "text", "text": m.content}]
            result.append(
                {
                    "id": m.id,
                    "role": m.role,
                    "parts": parts,
                    "created_at": m.created_at.isoformat() + "Z",
                }
            )
        return result

    @router.delete("/{id}")
    async def delete_conversation(id: str) -> Dict[str, Any]:
        deleted = conversation_store.delete(id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Conversation '{id}' not found")
        return {"id": id, "status": "deleted"}

    @router.post("/{id}/compact")
    async def compact_conversation(id: str) -> Dict[str, Any]:
        c = conversation_store.get(id)
        if c is None:
            raise HTTPException(status_code=404, detail=f"Conversation '{id}' not found")
        deleted_count = conversation_store.compact(id)
        return {"id": id, "deleted_count": deleted_count, "status": "compacted"}

    return router
