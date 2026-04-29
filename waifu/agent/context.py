import base64
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from shuvi.context import ContextManager
from shuvi.types import AppMessage
from waifu_types import Attachment, ConversationMode, HookContext, UserMessage

if TYPE_CHECKING:
    from waifu.config import ContextConfig
    from waifu.hook import HookRegistry

logger = logging.getLogger(__name__)


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


def _attachment_image_url(att: Attachment) -> str:
    """將 Attachment 轉為 image_url 字串（data URL 或遠端 URL）。"""
    if att.url:
        return att.url
    encoded = base64.b64encode(att.data).decode("utf-8")
    return f"data:{att.content_type};base64,{encoded}"


def _build_user_message(content: str, attachments: List[Attachment]) -> UserMessage:
    """將文字與圖片附件統一正規化為 multimodal content list。"""
    parts: List[Dict[str, Any]] = [{"type": "text", "text": content}]
    for att in attachments:
        if att.content_type.startswith("image/"):
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _attachment_image_url(att), "detail": "auto"},
                }
            )
    return UserMessage(content=parts)


class ContextBuilder:
    def __init__(self, config: "ContextConfig", hook_registry: "Optional[HookRegistry]" = None) -> None:
        self.config = config
        self._hook_registry = hook_registry

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

        if self._hook_registry is not None:
            for hook in self._hook_registry.hooks:
                fragment = hook.system_prompt_fragment(ctx)
                if fragment:
                    parts.append(fragment)

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
        cm.append(_build_user_message(content, ctx.request.attachments))

        return cm
