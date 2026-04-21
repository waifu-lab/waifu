import json
import logging
from typing import TYPE_CHECKING, Any, Dict, List

from hai.tool import Tool

if TYPE_CHECKING:
    from waifu.gateway.adapters.waifu_node import NodeSession, WaifuNodeAdapter
    from waifu.plugin import PluginRegistry

logger = logging.getLogger(__name__)


class NodeManager:
    """
    Node 子系統管理器（系統層，與 PluginManager 平級）

    職責：
    - node 連線時動態將其 tools 注入 PluginRegistry（永遠帶 @display_name 後綴）
    - node 斷線時移除對應 tools
    - 提供 tool_executor 供 node 透過 node_tool_call 反向呼叫 waifu tools
    """

    def __init__(self, plugin_registry: "PluginRegistry") -> None:
        self._registry = plugin_registry
        self._node_tools: Dict[str, List[str]] = {}  # node_id → registered tool names
        self._sessions: Dict[str, "NodeSession"] = {}  # node_id → NodeSession（用於重複名稱偵測）

    def wire(self, adapter: "WaifuNodeAdapter") -> None:
        """將 NodeManager 注入 WaifuNodeAdapter"""
        adapter.set_node_manager(self)

    def on_node_connect(self, session: "NodeSession") -> None:
        raw = (session.display_name or session.node_id).replace("-", "_").replace(" ", "_")
        suffix = f"__{raw}"

        existing_suffixes = {
            f"__{(s.display_name or s.node_id).replace('-', '_').replace(' ', '_')}"
            for nid, s in self._sessions.items() if nid != session.node_id
        }
        if suffix in existing_suffixes:
            logger.warning(
                "NodeManager: node %r has duplicate display_name %r — tool names will collide",
                session.node_id,
                session.display_name or session.node_id,
            )

        self._sessions[session.node_id] = session
        names: List[str] = []

        for schema in session.tools:
            action = schema.get("name", "")
            if not action:
                continue
            tool_name = f"node_{action}{suffix}"
            self._registry.add_tool(self._build_tool(tool_name, action, schema, session))
            names.append(tool_name)

        self._node_tools[session.node_id] = names
        logger.info(
            "NodeManager: node %r (%s) connected, registered tools=%s",
            session.node_id,
            session.display_name,
            names,
        )

    def on_node_disconnect(self, node_id: str) -> None:
        self._sessions.pop(node_id, None)
        for name in self._node_tools.pop(node_id, []):
            self._registry.remove_tool(name)
        logger.info("NodeManager: node %r disconnected, tools removed", node_id)

    @staticmethod
    def _build_tool(tool_name: str, action: str, schema: Dict[str, Any], session: "NodeSession") -> Tool:
        def make_func(s: "NodeSession", act: str):
            async def _call(**kwargs: Any) -> str:
                data = await s.invoke(act, kwargs)
                if isinstance(data, str):
                    return data
                return json.dumps(data, ensure_ascii=False)

            return _call

        return Tool(
            name=tool_name,
            description=schema.get("description", f"Node capability: {action}"),
            parameters=schema.get("parameters", {"type": "object", "properties": {}}),
            func=make_func(session, action),
        )

    def make_tool_executor(self):
        async def executor(tool_name: str, params: Dict[str, Any]) -> str:
            for tool in self._registry.get_all_tools():
                if tool.name == tool_name:
                    result = await tool.func(**params)
                    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            raise KeyError(f"tool '{tool_name}' not found in waifu registry")

        return executor
