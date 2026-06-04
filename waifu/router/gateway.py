from typing import Any, Dict

from fastapi import APIRouter

from waifu.service.gateway import GatewayConfigService


def make_gateway_router(gateway_config_service: GatewayConfigService) -> APIRouter:
    router = APIRouter(prefix="/gateway", tags=["gateway"])

    @router.get("/config")
    async def get_gateway_config() -> Dict[str, Any]:
        return {
            "path": str(gateway_config_service.path),
            "config": gateway_config_service.get_config(),
        }

    @router.put("/config")
    async def update_gateway_config(body: Dict[str, Any]) -> Dict[str, Any]:
        return gateway_config_service.update_config(body)

    @router.get("/adapters")
    async def get_gateway_adapters() -> Dict[str, Any]:
        return {"items": gateway_config_service.get_adapter_status()}

    return router
