from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from fastapi import FastAPI

from .health import router as health_router

if TYPE_CHECKING:
    from waifu.gateway.adapters.http import HTTPAdapter
    from waifu.gateway.adapters.waifu_node import WaifuNodeAdapter
    from waifu.gateway.adapters.websocket import WebSocketAdapter
    from waifu.gateway.session import SessionManager
    from waifu.plugin import PluginManager, PluginRegistry
    from waifu.service.character import CharacterService
    from waifu.service.config import AppConfigService
    from waifu.service.gateway import GatewayConfigService
    from waifu.service.mcp import MCPService
    from waifu.service.plugin import PluginService
    from waifu.service.skill import SkillService
    from waifu.store.conversation import ConversationStore
    from waifu.store.repositories.analytics import TokenAnalyticsRepository


def include_routers(
    app: FastAPI,
    *,
    ws_adapter: "WebSocketAdapter | None" = None,
    http_adapter: "HTTPAdapter | None" = None,
    waifu_node_adapter: "WaifuNodeAdapter | None" = None,
    plugin_service: "PluginService | None" = None,
    mcp_service: "MCPService | None" = None,
    skill_service: "SkillService | None" = None,
    config_service: "AppConfigService | None" = None,
    gateway_config_service: "GatewayConfigService | None" = None,
    character_service: "CharacterService | None" = None,
    cards_dir: "Path | None" = None,
    conversation_store: "ConversationStore | None" = None,
    attachments_dir: "Path | None" = None,
    plugin_registry: "PluginRegistry | None" = None,
    plugin_manager: "PluginManager | None" = None,
    session_manager: "SessionManager | None" = None,
    token_analytics: "TokenAnalyticsRepository | None" = None,
    get_started_at: "Callable[[], float] | None" = None,
    voice_enabled: bool = False,
    stt_enabled: bool = False,
    tts_enabled: bool = False,
) -> None:
    from .chat import make_chat_router
    from .plugin import make_plugin_router
    from .waifu_node import make_waifu_node_router
    from .ws import make_ws_router

    app.include_router(health_router)

    if ws_adapter is not None:
        app.include_router(make_ws_router(ws_adapter))

    if http_adapter is not None:
        app.include_router(make_chat_router(http_adapter))

    if waifu_node_adapter is not None:
        app.include_router(make_waifu_node_router(waifu_node_adapter))

    if plugin_service is not None:
        app.include_router(make_plugin_router(plugin_service))

    if mcp_service is not None:
        from .mcp import make_mcp_router

        app.include_router(make_mcp_router(mcp_service))

    if skill_service is not None:
        from .skill import make_skill_router

        app.include_router(make_skill_router(skill_service))

    if config_service is not None:
        from .config import make_config_router

        app.include_router(make_config_router(config_service))

    if gateway_config_service is not None:
        from .gateway import make_gateway_router

        app.include_router(make_gateway_router(gateway_config_service))

    if character_service is not None:
        from .character import make_character_router

        app.include_router(make_character_router(character_service, cards_dir=cards_dir))

    if conversation_store is not None:
        from .conversation import make_conversation_router

        app.include_router(make_conversation_router(conversation_store))

        if attachments_dir is not None:
            from .attachments import make_attachments_router

            app.include_router(make_attachments_router(conversation_store, attachments_dir))

    if plugin_registry is not None:
        from .tools import make_tools_router

        app.include_router(make_tools_router(plugin_registry))

    if session_manager is not None:
        from .session import make_session_router

        app.include_router(make_session_router(session_manager))

    if token_analytics is not None:
        from .analytics import make_analytics_router

        app.include_router(make_analytics_router(token_analytics))

    if (
        mcp_service is not None
        and config_service is not None
        and plugin_manager is not None
        and session_manager is not None
        and conversation_store is not None
    ):
        from waifu.service.status import StatusService

        from .status import make_status_router

        status_service = StatusService(
            get_started_at=get_started_at or (lambda: 0.0),
            session_manager=session_manager,
            conversation_store=conversation_store,
            plugin_manager=plugin_manager,
            mcp_service=mcp_service,
            config_service=config_service,
            gateway_config_service=gateway_config_service,
            voice_enabled=voice_enabled,
            stt_enabled=stt_enabled,
            tts_enabled=tts_enabled,
        )
        app.include_router(make_status_router(status_service))


__all__ = ["include_routers"]
