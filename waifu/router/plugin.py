from typing import Any, Dict, List, Optional, cast

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel as PydanticBaseModel

from waifu.service.plugin import PluginService

router = APIRouter(prefix="/plugins", tags=["plugins"])


class InstallPluginRequest(PydanticBaseModel):
    plugin_name: str
    config: Optional[Dict[str, Any]] = None


class UpdateConfigRequest(PydanticBaseModel):
    config: Dict[str, Any]


def make_plugin_router(plugin_service: PluginService) -> APIRouter:
    """建立並回傳綁定特定 PluginService 的 router"""

    @router.get("/")
    async def list_plugins() -> List[Dict[str, Any]]:
        return plugin_service.list_installed()

    @router.get("/available")
    async def list_available() -> List[Dict[str, Any]]:
        return [
            {"name": m.name, "version": m.version, "description": m.description, "config_schema": m.config_schema}
            for m in plugin_service.list_available()
        ]

    @router.post("/")
    async def install_plugin(body: InstallPluginRequest) -> Dict[str, str]:
        try:
            row = await plugin_service.install(body.plugin_name, body.config or {})
            return {"status": "installed", "name": cast(str, row.name)}
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    @router.post("/{name}/enable")
    async def enable_plugin(name: str) -> Dict[str, str]:
        try:
            await plugin_service.enable(name)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found") from e
        return {"status": "enabled", "name": name}

    @router.post("/{name}/disable")
    async def disable_plugin(name: str) -> Dict[str, str]:
        try:
            await plugin_service.disable(name)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found") from e
        return {"status": "disabled", "name": name}

    @router.delete("/{name}")
    async def uninstall_plugin(name: str) -> Dict[str, str]:
        try:
            await plugin_service.uninstall(name)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found") from e
        return {"status": "uninstalled", "name": name}

    return router
