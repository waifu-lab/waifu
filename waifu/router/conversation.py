import json
from datetime import datetime
from typing import Any, Dict, List, Optional, cast

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
                "id": cast(str, c.id),
                "title": cast(str, c.title),
                "created_at": cast(datetime, c.created_at).isoformat() + "Z",
                "updated_at": cast(datetime, c.updated_at).isoformat() + "Z",
                "message_count": len(conversation_store.get_messages(cast(str, c.id), limit=0)),
            }
            for c in convs
        ]

    @router.get("/{id}")
    async def get_conversation(id: str) -> Dict[str, Any]:
        c = conversation_store.get(id)
        if c is None:
            raise HTTPException(status_code=404, detail=f"Conversation '{id}' not found")
        return {
            "id": cast(str, c.id),
            "title": cast(str, c.title),
            "created_at": cast(datetime, c.created_at).isoformat() + "Z",
            "updated_at": cast(datetime, c.updated_at).isoformat() + "Z",
            "message_count": len(conversation_store.get_messages(cast(str, c.id), limit=0)),
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
                parts = json.loads(cast(str, m.content))
            except (json.JSONDecodeError, TypeError):
                parts = [{"type": "text", "text": cast(str, m.content)}]
            result.append(
                {
                    "id": cast(str, m.id),
                    "role": cast(str, m.role),
                    "parts": parts,
                    "attachments": conversation_store.attachments_for(cast(str, m.id)),
                    "created_at": cast(datetime, m.created_at).isoformat() + "Z",
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
