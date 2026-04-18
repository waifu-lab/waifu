import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict

from fastapi import APIRouter

from waifu.gateway.session import SessionManager
from waifu.plugin import PluginManager
from waifu.service.config import AppConfigService
from waifu.service.mcp import MCPService
from waifu.store.conversation import ConversationStore


def make_status_router(
    get_started_at: Callable[[], float],
    session_manager: SessionManager,
    conversation_store: ConversationStore,
    plugin_manager: PluginManager,
    mcp_service: MCPService,
    config_service: AppConfigService,
    voice_enabled: bool,
    stt_enabled: bool,
    tts_enabled: bool,
) -> APIRouter:
    router = APIRouter(tags=["status"])

    @router.get("/status")
    async def get_status() -> Dict[str, Any]:
        started = get_started_at()
        uptime = int(time.time() - started) if started else 0
        active_sessions = len(session_manager.list_all())
        active_conversations = conversation_store.count()

        plugins = plugin_manager.list()
        plugins_loaded = [p["name"] for p in plugins if p.get("state") == "enabled"]

        mcp_list = [
            {"name": r.name, "enabled": r.enabled}
            for r in mcp_service.list_all()
        ]

        cfg = config_service.get_all()

        return {
            "uptime_seconds": uptime,
            "active_sessions": active_sessions,
            "active_conversations": active_conversations,
            "plugins_loaded": plugins_loaded,
            "mcp_servers": mcp_list,
            "character": cfg.get("context.character"),
            "provider": {
                "model": cfg.get("provider.model"),
                "base_url": cfg.get("provider.base_url"),
            },
            "voice": {
                "enabled": voice_enabled,
                "stt_enabled": stt_enabled,
                "tts_enabled": tts_enabled,
            },
        }

    return router
