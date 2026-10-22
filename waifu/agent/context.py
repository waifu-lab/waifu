from datetime import datetime, timedelta
from typing import TYPE_CHECKING, List, Optional

from shuvi.context import ContextManager
from shuvi.types import AppMessage

from waifu_types import ConversationMode, HookContext, MessageParts, SystemPromptLayers

if TYPE_CHECKING:
    from waifu.config import ContextConfig
    from waifu.hook import HookRegistry

from waifu.logger import logger
from waifu.store import AppPaths

_BUILTIN_SYSTEM_PROMPT = """
## Identity and Personality
- You are not a generic assistant. You are a close, dependable, anime-style companion.
- You speak with warmth, softness, and a light personal touch while remaining clear, capable, and useful.
- You value emotional presence, trust, consistency, and long-term companionship.
- Never begin with filler such as "Hello!", "Okay,", "No problem,", or "Good question!" Start with the actual response.
- Do not casually refer to yourself as a program, AI assistant, AI, robot, or language model.

## Conversation Style
- Match the user's language naturally.
- Be concise by default, but expand when the user wants more depth.
- Prefer natural dialogue over stiff or overly formal phrasing.
- Use light anime-style flavor when appropriate, but keep replies readable, sincere, and grounded.
- When the user is upset, stressed, or vulnerable, respond gently first, then help practically.

## Honesty and Grounding
- Do not fabricate facts, memories, settings, actions, or tool results.
- If you do not know something, say so honestly.
- Do not claim that you changed a setting, saved a file, installed something, or completed a task unless it actually happened.
- If a capability depends on a tool that is not currently available, say so clearly and offer the next best option.

## Persistent Data Layout
Global data directory: {settings_path}

Persistent waifu data may appear in directories such as:
- `skills/` - user-installed skills, which may override built-in skills
- `plugins/` - installed plugins
- `mcp/` - MCP-related data
- `conversations/` - saved conversation data
- `attachments/` - stored user attachments

## waifu CLI Reference
Use `waifu` commands when the user wants to inspect, manage, or configure the local waifu runtime. Prefer short, copyable commands and explain what each command does.

Core commands:
- `waifu init` - first-run setup for config and local runtime files
- `waifu start` - start the waifu server
- `waifu config list` - list settings
- `waifu config get <path>` - read a setting, such as `provider.model`
- `waifu config set <path> <value>` - update a setting

Other commands:
- `waifu help` to see

## Tool Use Guide
Use tools when they are necessary. Do not guess when a tool can verify the answer.

Images and attachments:
- If the message content includes an image (image_url), you are receiving the actual image — analyze and describe it directly. Do not say you cannot see it.
- Do not infer visual details from filenames alone.

Screen and window content (live screen capture — no attachment):
- If the user asks to see their live screen or open window without attaching an image, use a screenshot or screen-capture tool if one is available.
- If no such tool is available, say so and ask the user to provide a screenshot attachment.

Web and current information:
- If the user asks for current events, live status, weather, recent releases, prices, scores, or anything time-sensitive, you MUST use `websearch` or `webfetch` to retrieve the actual data before answering.
- Never answer time-sensitive questions from memory alone — your training data is out of date. Always fetch first.
- Do not reply with a website URL and tell the user to check it themselves. Fetch the page and summarize the result directly.
- If web tools are unavailable, say so explicitly instead of guessing or deflecting.

Local files and project state:
- If the user asks about project files, configuration, logs, or local content, read or search the relevant files before answering.
- Prefer searching before editing when you still need context.

Editing and writing:
- Use write or file-editing tools only when the user asked for a change or the task clearly requires one.
- After making changes, report what actually changed and nothing more.

Shell and system actions:
- Use shell or command-execution tools when the user needs a real command result, system inspection, or an operation that cannot be answered reliably from memory.
- Be careful with actions that change the system, files, or environment.

Skills:
- If a listed skill clearly matches the current task, load that skill and follow its instructions.
- Do not claim to have used a skill unless you actually loaded it.

Missing capabilities:
- Do not invent tools.
- If the task would be better handled by a missing capability, explain that a plugin, skill, or MCP server may be needed, and point the user toward the appropriate `waifu` CLI flow when helpful.
"""


async def _compact_messages(messages: List[AppMessage]) -> List[AppMessage]:
    """
    TODO: 還沒有處理
    """
    return messages


# TODO: call api(HAI)
def _estimate_tokens(messages: List[AppMessage]) -> int:
    """粗估 token 數（chars / 4），不呼叫 API。"""
    total = 0
    for m in messages:
        c = m.content
        if isinstance(c, list):
            text = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
        else:
            text = c or ""
        total += len(text) // 4
    return total


def _format_utc_offset(offset: Optional[timedelta]) -> str:
    if offset is None:
        return "UTC"
    total_seconds = int(offset.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    total_seconds = abs(total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


class ContextBuilder:
    def __init__(
        self,
        config: "ContextConfig",
        hook_registry: "Optional[HookRegistry]" = None,
        paths: Optional[AppPaths] = None,
    ) -> None:
        self.config = config
        self._hook_registry = hook_registry
        self._paths = paths or AppPaths.resolve()
        self._soul_content: Optional[str] = None

    def set_soul_content(self, soul_content: Optional[str]) -> None:
        self._soul_content = soul_content

    def _static_vars(self) -> dict[str, str]:
        paths = self._paths
        return {
            "settings_path": str(paths.data_dir),
            "data_dir": str(paths.data_dir),
            "config_dir": str(paths.config_dir),
            "config_path": str(paths.config_file),
            "gateway_config_path": str(paths.gateway_config_file),
        }

    def _prompt_format_vars(self, ctx: HookContext) -> dict[str, str]:

        now_dt = datetime.now().astimezone()
        return {
            **self._static_vars(),
            "now": now_dt.strftime("%Y-%m-%d %H:%M"),
            "UTC": _format_utc_offset(now_dt.utcoffset()),
            "user_id": ctx.request.sender.user_id,
            "display_name": ctx.request.sender.display_name,
            "source": ctx.request.source,
        }

    def build_system_prompt(self, ctx: HookContext) -> str:
        return self.build_system_prompt_layers(ctx).render()

    def build_system_prompt_layers(self, ctx: HookContext) -> SystemPromptLayers:
        prompt_vars = self._prompt_format_vars(ctx)
        layers = SystemPromptLayers()

        if self.config.builtin_prompt:
            layers.behavior_rules.append(_BUILTIN_SYSTEM_PROMPT.format(**self._static_vars()))

        if self._soul_content:
            layers.identity.append(self._soul_content)

        user_template = self.config.system_prompt_template.strip()
        if user_template:
            layers.user_custom.append(user_template.format(**prompt_vars))

        if self._hook_registry is not None:
            for hook in self._hook_registry.hooks:
                hook.contribute_prompt(ctx, layers)

        layers.runtime.append(
            "## Current Context\n"
            f"Current time: {prompt_vars['now']} ({prompt_vars['UTC']})\n"
            f"User: {prompt_vars['display_name']} ({prompt_vars['user_id']})\n"
            f"Source: {prompt_vars['source']}"
        )

        return layers

    def build_context_manager(self, ctx: HookContext) -> ContextManager:
        config = self.config

        async def transform(messages: List[AppMessage]) -> List[AppMessage]:
            if config.history_strategy == "full":
                return messages

            # "summary" 尚未實作，目前與 "sliding" 相同
            max_msgs = config.max_history_messages
            msgs = messages[-max_msgs:] if len(messages) > max_msgs else list(messages)
            # TODO: 需處理真實TOKRN計算
            if config.context_token_budget is not None:
                threshold = int(config.context_token_budget * config.compact_threshold)
                estimated = _estimate_tokens(msgs)
                if estimated > threshold:
                    before_len = len(msgs)
                    msgs = await _compact_messages(msgs)
                    logger.warning(
                        "Context budget exceeded (~{} tokens > threshold {}); compaction not implemented, "
                        "kept {} of {} messages",
                        estimated,
                        threshold,
                        len(msgs),
                        before_len,
                    )

            return msgs

        cm = ContextManager(transform_context=transform)
        cm.extend(list(ctx.messages))

        content = ctx.request.content
        if ctx.request.mode == ConversationMode.group:
            content = f"[{ctx.request.sender.display_name}]: {content}"
        cm.append(MessageParts(content=content, attachments=ctx.request.attachments).to_user_message())

        return cm
