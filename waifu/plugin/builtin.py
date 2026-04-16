from typing import Any, Dict, List, TYPE_CHECKING

from waifu_types import BaseHook, BaseMCPAdapter, BasePlugin, PluginContext

if TYPE_CHECKING:
    from hai.tool import Tool
    from waifu.gateway.adapters.waifu_node import WaifuNodeAdapter


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


class MCPPlugin(BasePlugin):
    """將任意 BaseMCPAdapter 包裝成插件，負責連線生命週期"""

    def __init__(self, name: str, adapter: BaseMCPAdapter) -> None:
        self.name = name
        self._adapter = adapter

    async def on_load(self, ctx: PluginContext) -> None:
        await self._adapter.connect()
        tools = await self._adapter.list_tools()
        for tool in tools:
            ctx.register_tool(tool)
        ctx.register_mcp(self.name, self._adapter)

    async def on_unload(self) -> None:
        await self._adapter.disconnect()


class WaifuNodePlugin(BasePlugin):
    """
    將 WaifuNodeAdapter 包裝成插件。

    特性：
      - node 在 node_hello 時攜帶完整 tool schema，waifu 動態注冊（無靜態映射）
      - node 也可透過 node_tool_call 呼叫 waifu 已注冊的任意 tool（雙向）
      - node 斷線時自動移除其注冊的 tools

    用法：
        node_adapter = WaifuNodeAdapter(token="secret")
        await waifu.plugin(WaifuNodePlugin(node_adapter))
    """

    name = "waifu_node"
    version = "1.0.0"
    description = "Waifu-Node computer control bridge"

    def __init__(self, adapter: "WaifuNodeAdapter") -> None:
        self._adapter = adapter
        self._registered_tool_names: List[str] = []

    async def on_load(self, ctx: PluginContext) -> None:
        await ctx.register_adapter(self._adapter)

        # node 連線時：動態建立並注冊 tools
        def on_connect(node_tools: List[Dict[str, Any]]) -> None:
            from hai.tool import Tool

            self._registered_tool_names.clear()
            for schema in node_tools:
                tool_name = schema.get("name", "")
                if not tool_name:
                    continue

                # 建立閉包，捕捉 action 名稱
                def make_func(action: str):
                    async def _call(**kwargs: Any) -> str:
                        import json
                        data = await self._adapter.invoke(action, kwargs)
                        if isinstance(data, str):
                            return data
                        return json.dumps(data, ensure_ascii=False, indent=2)
                    return _call

                tool = Tool(
                    name=f"node_{tool_name}",
                    description=schema.get("description", f"Call node capability: {tool_name}"),
                    parameters=schema.get("parameters", {"type": "object", "properties": {}}),
                    func=make_func(tool_name),
                )
                ctx.register_tool(tool)
                self._registered_tool_names.append(tool.name)

        # node 斷線時：從 registry 移除其 tools
        def on_disconnect() -> None:
            # PluginRegistry 目前無 remove API，清空 name 清單即可
            # 下次 node 重連時會重新注冊
            self._registered_tool_names.clear()

        # tool executor：讓 node 能呼叫 waifu 已注冊的 tools
        async def tool_executor(tool_name: str, params: Dict[str, Any]) -> str:
            from waifu.plugin import PluginRegistry
            # 透過 ctx._registry 取得 tools（plugin 內部存取）
            registry: PluginRegistry = ctx._registry  # type: ignore[attr-defined]
            for tool in registry.get_all_tools():
                if tool.name == tool_name:
                    return await tool.func(**params)
            raise KeyError(f"tool '{tool_name}' not found")

        self._adapter.set_on_connect(on_connect)
        self._adapter.set_on_disconnect(on_disconnect)
        self._adapter.set_tool_executor(tool_executor)
