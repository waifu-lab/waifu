from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel as PydanticBaseModel

from waifu.service.skill import SkillService
from waifu.skill.installer import SkillInstallError
from waifu.skill.manifest import SkillParseError

router = APIRouter(prefix="/skill", tags=["skill"])


class InstallSkillRequest(PydanticBaseModel):
    source: str
    overwrite: bool = False


def make_skill_router(service: SkillService) -> APIRouter:
    @router.get("/")
    async def list_skills() -> List[Dict[str, Any]]:
        return service.list()

    @router.post("/install")
    async def install_skill(body: InstallSkillRequest) -> Dict[str, Any]:
        try:
            return service.install(body.source, overwrite=body.overwrite)
        except (SkillInstallError, SkillParseError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @router.delete("/{name}")
    async def uninstall_skill(name: str) -> Dict[str, str]:
        try:
            service.uninstall(name)
        except SkillInstallError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return {"status": "uninstalled", "name": name}

    @router.post("/reload")
    async def reload_skills() -> Dict[str, Any]:
        count = service.reload()
        return {"status": "reloaded", "count": count}

    return router
