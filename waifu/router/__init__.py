from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI

from .health import router as health_router

if TYPE_CHECKING:
    from waifu.gateway.session import SessionManager
    from waifu.plugin import PluginRegistry
    from waifu.service.character import CharacterService
    from waifu.service.config import AppConfigService
    from waifu.service.gateway import GatewayConfigService
    from waifu.service.mcp import MCPService
    from waifu.service.plugin import PluginService
    from waifu.service.skill import SkillService
    from waifu.service.status import StatusService
    from waifu.store.conversation import ConversationStore
    from waifu.store.repositories.analytics import TokenAnalyticsRepository


def include_routers(
    app: FastAPI,
    *,
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
    session_manager: "SessionManager | None" = None,
    token_analytics: "TokenAnalyticsRepository | None" = None,
    status_service: "StatusService | None" = None,
) -> None:
    """掛載管理 API；adapter 的 endpoint（/ws、/chat、/node）由 BaseGatewayAdapter.routers() 提供"""
    from .plugin import make_plugin_router

    app.include_router(health_router)

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

    if status_service is not None:
        from .status import make_status_router

        app.include_router(make_status_router(status_service))


__all__ = ["include_routers"]
