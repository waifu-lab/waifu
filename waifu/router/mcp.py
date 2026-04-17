from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel as PydanticBaseModel

from waifu.service.mcp import MCPService

router = APIRouter(prefix="/mcp", tags=["mcp"])


class AddMCPRequest(PydanticBaseModel):
    name: str
    type: str  # "stdio" | "sse"
    command: Optional[List[str]] = None
    url: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class UpdateMCPRequest(PydanticBaseModel):
    type: Optional[str] = None
    command: Optional[List[str]] = None
    url: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


def make_mcp_router(mcp_service: MCPService) -> APIRouter:
    @router.get("/")
    async def list_mcp() -> List[Dict[str, Any]]:
        return [{"name": r.name, "type": r.type, "enabled": r.enabled} for r in mcp_service.list_all()]

    @router.post("/")
    async def add_mcp(body: AddMCPRequest) -> Dict[str, str]:
        try:
            row = await mcp_service.add(body.name, body.type, body.command, body.url, body.config)
            return {"status": "added", "name": row.name}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    @router.post("/{name}/enable")
    async def enable_mcp(name: str) -> Dict[str, str]:
        try:
            await mcp_service.enable(name)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found") from e
        return {"status": "enabled", "name": name}

    @router.post("/{name}/disable")
    async def disable_mcp(name: str) -> Dict[str, str]:
        try:
            await mcp_service.disable(name)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found") from e
        return {"status": "disabled", "name": name}

    @router.delete("/{name}")
    async def remove_mcp(name: str) -> Dict[str, str]:
        try:
            await mcp_service.remove(name)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found") from e
        return {"status": "removed", "name": name}

    return router
