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

    include_routers(
        app,
        ws_adapter=ws_adapter,
        http_adapter=http_adapter,
        plugin_manager=waifu.plugin_manager,
    )

    app.state.waifu = waifu
    await waifu.start()

    yield


app = FastAPI(title="Waifu", version=__version__, lifespan=_lifespan)
