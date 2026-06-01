from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from waifu import Waifu, __version__
from waifu.config import WaifuConfig
from waifu.gateway.adapters import HTTPAdapter, WebSocketAdapter
from waifu.router import include_routers

_config: Optional[WaifuConfig] = None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    assert _config is not None, "_cli_app._config must be set before uvicorn starts"

    waifu = Waifu(_config)

    ws_adapter = WebSocketAdapter(voice_service=waifu.voice_service)
    http_adapter = HTTPAdapter()

    waifu.mount(ws_adapter).mount(http_adapter)

    # Waifu-Node：若 config 啟用則自動掛載
    waifu_node_adapter = None
    if _config.node is not None and _config.node.enabled:
        from waifu.gateway.adapters import WaifuNodeAdapter

        waifu_node_adapter = WaifuNodeAdapter(
            token=_config.node.token,
            invoke_timeout_ms=_config.node.invoke_timeout_ms,
            ping_interval_s=_config.node.ping_interval_s,
        )
        waifu.mount(waifu_node_adapter)
    include_routers(
        app,
        ws_adapter=ws_adapter,
        http_adapter=http_adapter,
        waifu_node_adapter=waifu_node_adapter,
        plugin_service=waifu.plugin_service,
        mcp_service=waifu.mcp_service,
        skill_service=waifu.skill_service,
        config_service=waifu.config_service,
        character_service=waifu.character_service,
        cards_dir=waifu.paths.cards_dir,
        conversation_store=waifu.conversation_store,
        attachments_dir=waifu.paths.attachments_dir,
        plugin_registry=waifu.plugin_registry,
        plugin_manager=waifu.plugin_manager,
        session_manager=waifu.gateway.session_manager,
        token_analytics=waifu.token_analytics,
        get_started_at=lambda: waifu.started_at,
        voice_enabled=waifu.voice_service is not None,
        stt_enabled=waifu.voice_service is not None and waifu.voice_service.has_stt,
        tts_enabled=waifu.voice_service is not None and waifu.voice_service.has_tts,
    )

    app.state.waifu = waifu

    await waifu.start()

    yield


app = FastAPI(title="Waifu", version=__version__, lifespan=_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
