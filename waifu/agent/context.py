from datetime import datetime
from typing import Any, Dict, List, TYPE_CHECKING

from pydantic import BaseModel
from waifu_types import ConversationMode, HookContext

if TYPE_CHECKING:
    from waifu.config import ContextConfig
    from waifu.plugin import PluginRegistry


class AgentInput(BaseModel):
    system_prompt: str
    messages: List[Dict[str, Any]]
    tools: List[Any]  # hai.tool.Tool


class ContextBuilder:
    """
    組裝 AgentInput：
    1. system_prompt（模板渲染 + 當前時間）
    2. messages（歷史 + 當前輸入，GROUP 模式加 [DisplayName]: 前綴）
    3. tools（PluginRegistry.get_all_tools()）
    """

    def __init__(self, config: "ContextConfig") -> None:
        self._config = config

    async def build(self, ctx: HookContext, plugin_registry: "PluginRegistry") -> AgentInput:
        system_prompt = self._build_system_prompt(ctx)
        messages = self._build_messages(ctx)
        tools = plugin_registry.get_all_tools()
        return AgentInput(system_prompt=system_prompt, messages=messages, tools=tools)

    # ── 內部 ──────────────────────────────────────────────────────────────

    def _build_system_prompt(self, ctx: HookContext) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        template = self._config.system_prompt_template
        return template.format(
            now=now,
            user_id=ctx.request.sender.user_id,
            display_name=ctx.request.sender.display_name,
            source=ctx.request.source,
        )

    def _build_messages(self, ctx: HookContext) -> List[Dict[str, Any]]:
        history = self._apply_history_strategy(ctx.messages)

        current_content = ctx.request.content
        if ctx.request.mode == ConversationMode.group:
            current_content = f"[{ctx.request.sender.display_name}]: {current_content}"

        return history + [{"role": "user", "content": current_content}]

    def _apply_history_strategy(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        strategy = self._config.history_strategy
        max_msgs = self._config.max_history_messages

        if strategy == "full":
            return list(messages)
        # sliding window（default）
        return list(messages[-max_msgs:]) if len(messages) > max_msgs else list(messages)
