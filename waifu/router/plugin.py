from typing import TYPE_CHECKING, Any, Dict, List

from fastapi import APIRouter, HTTPException

if TYPE_CHECKING:
    from waifu.plugin import PluginManager

router = APIRouter(prefix="/plugins", tags=["plugins"])


def make_plugin_router(plugin_manager: "PluginManager") -> APIRouter:
    """建立並回傳綁定特定 PluginManager 的 router"""

    @router.get("/")
    async def list_plugins() -> List[Dict[str, Any]]:
        return plugin_manager.list()

    @router.post("/{name}/enable")
    async def enable_plugin(name: str) -> Dict[str, str]:
        try:
            await plugin_manager.enable(name)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found")
        return {"status": "enabled", "name": name}

    @router.post("/{name}/disable")
    async def disable_plugin(name: str) -> Dict[str, str]:
        try:
            await plugin_manager.disable(name)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found")
        return {"status": "disabled", "name": name}

    @router.delete("/{name}")
    async def unload_plugin(name: str) -> Dict[str, str]:
        try:
            await plugin_manager.unload(name)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found")
        return {"status": "unloaded", "name": name}

    return router
