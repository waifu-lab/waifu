from typing import Any, Dict, List

from fastapi import APIRouter

from waifu.plugin import PluginRegistry


def make_tools_router(plugin_registry: PluginRegistry) -> APIRouter:
    router = APIRouter(tags=["tools"])

    @router.get("/tools")
    async def list_tools() -> List[Dict[str, Any]]:
        tools = plugin_registry.get_all_tools()
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            }
            for t in tools
        ]

    return router
