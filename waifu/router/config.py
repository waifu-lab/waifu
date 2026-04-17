from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from waifu.service.config import AppConfigService

router = APIRouter(prefix="/config", tags=["config"])


def make_config_router(config_service: AppConfigService) -> APIRouter:
    @router.get("/")
    async def get_all_config() -> Dict[str, Any]:
        return config_service.get_all()

    @router.put("/")
    async def batch_update_config(body: Dict[str, Any]) -> Dict[str, Any]:
        results = {}
        for key, value in body.items():
            result = config_service.set(key, value)
            results[key] = result
        return results

    @router.get("/{key:path}")
    async def get_config(key: str) -> Dict[str, Any]:
        value = config_service.get(key)
        if value is None:
            raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")
        return {"key": key, "value": value}

    @router.put("/{key:path}")
    async def set_config(key: str, body: Dict[str, Any]) -> Dict[str, Any]:
        value = body.get("value")
        return config_service.set(key, value)

    return router
