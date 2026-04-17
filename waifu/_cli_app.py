from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI

from waifu import Waifu, __version__
from waifu.config import WaifuConfig
from waifu.gateway.adapters import HTTPAdapter, WebSocketAdapter
from waifu.router import include_routers

_config: Optional[WaifuConfig] = None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    assert _config is not None, "_cli_app._config must be set before uvicorn starts"

    ws_adapter = WebSocketAdapter()
    http_adapter = HTTPAdapter()

    waifu = Waifu(_config)
    waifu.mount(ws_adapter).mount(http_adapter)

    # Waifu-Node：若 config 啟用則自動掛載
    waifu_node_adapter = None
    if _config.node is not None and _config.node.enabled:
        from waifu.gateway.adapters import WaifuNodeAdapter
        from waifu.plugin.builtin import WaifuNodePlugin

        waifu_node_adapter = WaifuNodeAdapter(
            token=_config.node.token,
            invoke_timeout_ms=_config.node.invoke_timeout_ms,
            ping_interval_s=_config.node.ping_interval_s,
        )
        await waifu.plugin(WaifuNodePlugin(waifu_node_adapter))

    include_routers(
        app,
        ws_adapter=ws_adapter,
        http_adapter=http_adapter,
        waifu_node_adapter=waifu_node_adapter,
        plugin_service=waifu.plugin_service,
        mcp_service=waifu.mcp_service,
        config_service=waifu.config_service,
        character_service=waifu.character_service,
    )

    app.state.waifu = waifu
    await waifu.start()

    yield


app = FastAPI(title="Waifu", version=__version__, lifespan=_lifespan)
