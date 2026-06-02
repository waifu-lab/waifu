import time
from typing import Any, Callable, Dict, List

from waifu.gateway.session import SessionManager
from waifu.plugin import PluginManager
from waifu.service.config import AppConfigService
from waifu.service.mcp import MCPService
from waifu.store.conversation import ConversationStore


class StatusService:
    def __init__(
        self,
        *,
        get_started_at: Callable[[], float],
        session_manager: SessionManager,
        conversation_store: ConversationStore,
        plugin_manager: PluginManager,
        mcp_service: MCPService,
        config_service: AppConfigService,
        voice_enabled: bool,
        stt_enabled: bool,
        tts_enabled: bool,
    ) -> None:
        self._get_started_at = get_started_at
        self._session_manager = session_manager
        self._conversation_store = conversation_store
        self._plugin_manager = plugin_manager
        self._mcp_service = mcp_service
        self._config_service = config_service
        self._voice_enabled = voice_enabled
        self._stt_enabled = stt_enabled
        self._tts_enabled = tts_enabled

    def get_status(self) -> Dict[str, Any]:
        started = self._get_started_at()
        uptime = int(time.time() - started) if started else 0
        active_sessions = len(self._session_manager.list_all())
        active_conversations = self._conversation_store.count()

        plugins = self._plugin_manager.list()
        plugins_loaded = [p["name"] for p in plugins if p.get("state") == "enabled"]

        mcp_list: List[Dict[str, Any]] = [
            {"name": r.get("name"), "enabled": r.get("enabled", True)} for r in self._mcp_service.list_all()
        ]

        cfg = self._config_service.get_all()

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
                "enabled": self._voice_enabled,
                "stt_enabled": self._stt_enabled,
                "tts_enabled": self._tts_enabled,
            },
        }
