from fastapi import APIRouter

from waifu.service.status import StatusService


def make_status_router(status_service: StatusService) -> APIRouter:
    router = APIRouter(tags=["status"])

    @router.get("/status")
    async def get_status():
        return status_service.get_status()

    return router
