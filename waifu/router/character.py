from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel as PydanticBaseModel

from waifu.service.character import CharacterService

router = APIRouter(prefix="/characters", tags=["characters"])


class CreateCharacterRequest(PydanticBaseModel):
    name: str
    soul_path: str
    avatar_path: Optional[str] = None
    live2d_dir: Optional[str] = None


class UpdateCharacterRequest(PydanticBaseModel):
    name: Optional[str] = None
    soul_path: Optional[str] = None
    avatar_path: Optional[str] = None
    live2d_dir: Optional[str] = None


class UpdateRelationshipRequest(PydanticBaseModel):
    display_name: Optional[str] = None
    notes: Optional[str] = None
    memory_path: Optional[str] = None


def make_character_router(character_service: CharacterService) -> APIRouter:
    @router.get("/")
    async def list_characters() -> List[Dict[str, Any]]:
        return [
            {
                "id": c.id,
                "name": c.name,
                "soul_path": c.soul_path,
                "avatar_path": c.avatar_path,
                "live2d_dir": c.live2d_dir,
                "active": c.active,
            }
            for c in character_service.list_all()
        ]

    @router.post("/")
    async def create_character(body: CreateCharacterRequest) -> Dict[str, Any]:
        char = character_service.create(body.name, body.soul_path, body.avatar_path, body.live2d_dir)
        return {"id": char.id, "name": char.name, "status": "created"}

    @router.get("/{id}")
    async def get_character(id: str) -> Dict[str, Any]:
        char = character_service.get(id)
        if char is None:
            raise HTTPException(status_code=404, detail=f"Character '{id}' not found")
        return {
            "id": char.id,
            "name": char.name,
            "soul_path": char.soul_path,
            "avatar_path": char.avatar_path,
            "live2d_dir": char.live2d_dir,
            "active": char.active,
        }

    @router.put("/{id}")
    async def update_character(id: str, body: UpdateCharacterRequest) -> Dict[str, str]:
        fields = body.model_dump(exclude_none=True)
        if not fields:
            raise HTTPException(status_code=400, detail="No fields to update")
        character_service.update(id, **fields)
        return {"id": id, "status": "updated"}

    @router.delete("/{id}")
    async def delete_character(id: str) -> Dict[str, str]:
        character_service.delete(id)
        return {"id": id, "status": "deleted"}

    @router.post("/{id}/activate")
    async def activate_character(id: str) -> Dict[str, str]:
        character_service.activate(id)
        return {"id": id, "status": "activated"}

    @router.get("/{id}/relationships")
    async def list_relationships(id: str) -> List[Dict[str, Any]]:
        return [
            {
                "user_id": r.user_id,
                "display_name": r.display_name,
                "notes": r.notes,
                "memory_path": r.memory_path,
            }
            for r in character_service.list_relationships(id)
        ]

    @router.get("/{id}/relationships/{uid}")
    async def get_relationship(id: str, uid: str) -> Dict[str, Any]:
        rel = character_service.get_relationship_detail(id, uid)
        if rel is None:
            raise HTTPException(status_code=404, detail="Relationship not found")
        return {
            "user_id": rel.user_id,
            "display_name": rel.display_name,
            "notes": rel.notes,
            "memory_path": rel.memory_path,
        }

    @router.put("/{id}/relationships/{uid}")
    async def update_relationship(id: str, uid: str, body: UpdateRelationshipRequest) -> Dict[str, str]:
        fields = body.model_dump(exclude_none=True)
        if not fields:
            raise HTTPException(status_code=400, detail="No fields to update")
        character_service.update_relationship(id, uid, **fields)
        return {"status": "updated"}

    return router
