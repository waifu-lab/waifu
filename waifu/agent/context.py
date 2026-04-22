import logging
from datetime import datetime
from typing import TYPE_CHECKING, List

from shuvi.context import ContextManager
from shuvi.types import AppMessage
from waifu_types import ConversationMode, HookContext, UserMessage

if TYPE_CHECKING:
    from waifu.config import ContextConfig

logger = logging.getLogger(__name__)


def _estimate_tokens(messages: List[AppMessage]) -> int:
    """粗估 token 數（chars / 4），不呼叫 API。"""
    total = 0
    for m in messages:
        content = m.content or ""
        total += len(content) // 4
    return total


class ContextBuilder:
    def __init__(self, config: "ContextConfig") -> None:
        self.config = config

    def build_system_prompt(self, ctx: HookContext) -> str:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        parts: List[str] = []

        if self.config.soul_content:
            parts.append(self.config.soul_content)
        else:
            template = self.config.system_prompt_template
            parts.append(
                template.format(
                    now=now,
                    user_id=ctx.request.sender.user_id,
                    display_name=ctx.request.sender.display_name,
                    source=ctx.request.source,
                )
            )

        relationship = ctx.metadata.get("relationship", "")
        if relationship:
            parts.append(f"## 與當前對話者的關係\n{relationship}")

        parts.append(f"當前對話者: {ctx.request.sender.display_name} ({ctx.request.sender.user_id})\n當前時間: {now}")

        return "\n\n".join(parts)

    def build_context_manager(self, ctx: HookContext) -> ContextManager:
        config = self.config

        async def transform(messages: List[AppMessage]) -> List[AppMessage]:
            if config.history_strategy == "full":
                return messages

            max_msgs = config.max_history_messages
            msgs = messages[-max_msgs:] if len(messages) > max_msgs else list(messages)

            # 粗估 chars/4
            if config.context_token_budget is not None:
                threshold = int(config.context_token_budget * config.compact_threshold)
                before = _estimate_tokens(msgs)
                while len(msgs) >= 2 and _estimate_tokens(msgs) > threshold:
                    msgs = msgs[2:]
                after = _estimate_tokens(msgs)
                if after < before:
                    logger.warning(
                        "Context budget exceeded (%d tokens > %d threshold): trimmed from %d to %d messages",
                        before,
                        threshold,
                        len(msgs) + (before - after),
                        len(msgs),
                    )

            return msgs

        cm = ContextManager(transform_context=transform)
        cm.extend(list(ctx.messages))

        content = ctx.request.content
        if ctx.request.mode == ConversationMode.group:
            content = f"[{ctx.request.sender.display_name}]: {content}"
        cm.append(UserMessage(content=content))

        return cm
