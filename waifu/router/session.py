import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from waifu.gateway.session import SessionManager


def make_session_router(session_manager: SessionManager) -> APIRouter:
    router = APIRouter(prefix="/sessions", tags=["sessions"])

    @router.get("/")
    async def list_sessions() -> List[Dict[str, Any]]:
        sessions = session_manager.list_all()
        return [
            {
                "conversation_id": s.conversation_id,
                "message_count": len(s.history),
                "metadata": s.metadata,
                "last_active": datetime.fromtimestamp(s.last_active, tz=timezone.utc).isoformat(),
            }
            for s in sessions
        ]

    @router.delete("/{conversation_id}")
    async def clear_session(conversation_id: str) -> Dict[str, str]:
        session = session_manager.get(conversation_id)
        if session is None:
            raise HTTPException(
                status_code=404,
                detail=f"Session '{conversation_id}' not found",
            )
        session_manager.delete(conversation_id)
        return {"conversation_id": conversation_id, "status": "cleared"}

    return router
