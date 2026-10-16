import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from waifu import Waifu, __version__
from waifu.config import WaifuConfig
from waifu.gateway.config import GatewayRuntimeConfig
from waifu.logger import setup_logging
from waifu.router import include_routers
from waifu.service.gateway import GatewayConfigService
from waifu.store.paths import AppPaths

_config: Optional[WaifuConfig] = None
_gateway_config: Optional[GatewayRuntimeConfig] = None
_paths: Optional[AppPaths] = None
_config_path: Optional[Path] = None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    setup_logging(level=os.getenv("WAIFU_LOG_LEVEL", "INFO"))

    assert _config is not None, "_cli_app._config must be set before uvicorn starts"
    assert _gateway_config is not None, "_cli_app._gateway_config must be set before uvicorn starts"
    assert _paths is not None, "_cli_app._paths must be set before uvicorn starts"

    gateway_config_service = GatewayConfigService(_paths.gateway_config_file, _gateway_config)
    waifu = Waifu(_config, paths=_paths, gateway_config_service=gateway_config_service, config_path=_config_path)

    for adapter in gateway_config_service.build_runtime_adapters(voice_service=waifu.voice_service):
        waifu.mount(adapter)

    if _config.node is not None and _config.node.enabled:
        from waifu.gateway.adapters import WaifuNodeAdapter

        waifu.mount(
            WaifuNodeAdapter(
                token=_config.node.token,
                invoke_timeout_ms=_config.node.invoke_timeout_ms,
                ping_interval_s=_config.node.ping_interval_s,
                path=_config.node.path,
            )
        )

    for adapter in waifu.gateway.adapters:
        for router in adapter.routers():
            app.include_router(router)

    include_routers(
        app,
        plugin_service=waifu.plugin_service,
        mcp_service=waifu.mcp_service,
        skill_service=waifu.skill_service,
        config_service=waifu.config_service,
        gateway_config_service=gateway_config_service,
        character_service=waifu.character_service,
        cards_dir=waifu.paths.cards_dir,
        conversation_store=waifu.conversation_store,
        attachments_dir=waifu.paths.attachments_dir,
        plugin_registry=waifu.plugin_registry,
        session_manager=waifu.gateway.session_manager,
        token_analytics=waifu.token_analytics,
        status_service=waifu.status_service,
    )

    app.state.waifu = waifu
    app.state.gateway_config = gateway_config_service.get_config()

    await waifu.start()

    yield


app = FastAPI(title="Waifu", version=__version__, lifespan=_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
