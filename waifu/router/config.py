from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from waifu.config.sync import ConfigError
from waifu.service.config import AppConfigService


def make_config_router(config_service: AppConfigService) -> APIRouter:
    router = APIRouter(prefix="/config", tags=["config"])

    def _set(key: str, value: Any) -> Dict[str, Any]:
        try:
            return config_service.set(key, value)
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid config for '{key}': {exc}") from exc

    @router.get("/")
    async def get_all_config() -> Dict[str, Any]:
        return config_service.get_all()

    @router.put("/")
    async def batch_update_config(body: Dict[str, Any]) -> Dict[str, Any]:
        return {key: _set(key, value) for key, value in body.items()}

    @router.get("/{key:path}")
    async def get_config(key: str) -> Dict[str, Any]:
        value = config_service.get(key)
        if value is None:
            raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")
        return {"key": key, "value": value}

    @router.put("/{key:path}")
    async def set_config(key: str, body: Dict[str, Any]) -> Dict[str, Any]:
        return _set(key, body.get("value"))

    return router
