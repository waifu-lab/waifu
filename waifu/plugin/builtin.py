from typing import TYPE_CHECKING, List

from waifu_types import BaseHook, BasePlugin, PluginContext

if TYPE_CHECKING:
    from hai.tool import Tool


class ToolPlugin(BasePlugin):
    """將一組本地 Tool 包裝成插件，方便動態載入/卸載"""

    def __init__(self, name: str, tools: List["Tool"]) -> None:
        self.name = name
        self._tools = tools

    async def on_load(self, ctx: PluginContext) -> None:
        for tool in self._tools:
            ctx.register_tool(tool)


class HookPlugin(BasePlugin):
    """將 Hook 包裝成插件，方便動態啟停"""

    def __init__(self, hook: BaseHook) -> None:
        self.name = f"hook:{hook.name}"
        self._hook = hook

    async def on_load(self, ctx: PluginContext) -> None:
        ctx.register_hook(self._hook)
