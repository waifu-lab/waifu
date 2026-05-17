import base64
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from shuvi.context import ContextManager
from shuvi.types import AppMessage
from waifu_types import Attachment, ConversationMode, HookContext, SystemPromptLayers, UserMessage

if TYPE_CHECKING:
    from waifu.config import ContextConfig
    from waifu.hook import HookRegistry

from waifu.logger import logger


async def _compact_messages(messages: List[AppMessage]) -> List[AppMessage]:
    """
    TODO: 還沒有處理
    """
    return messages


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


# FIXME: 好醜
_SUPPORTED_FILE_TYPES = {
    "application/pdf",
    "text/plain",
    "text/html",
    "text/css",
    "text/javascript",
    "text/markdown",
    "application/json",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # docx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # xlsx
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # pptx
    "application/msword",
    "text/csv",
    "text/xml",
    "application/xml",
}


def _to_data_url(att: Attachment) -> str:
    if att.url:
        return att.url
    encoded = base64.b64encode(att.data).decode("utf-8")
    return f"data:{att.content_type};base64,{encoded}"


def _build_user_message(content: str, attachments: List[Attachment]) -> UserMessage:
    parts: List[Dict[str, Any]] = [{"type": "text", "text": content}]
    for att in attachments:
        if att.content_type.startswith("image/"):
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": _to_data_url(att), "detail": "auto"},
                }
            )
        elif att.content_type in _SUPPORTED_FILE_TYPES:
            if not att.data and not att.url:
                logger.warning("Attachment '{}' has no data or url, skipping", att.filename)
                continue
            parts.append(
                {
                    "type": "file",
                    "file": {
                        "filename": att.filename,
                        "file_data": _to_data_url(att),
                    },
                }
            )
        else:
            logger.warning("Unsupported attachment type '{}' ({}), skipping", att.content_type, att.filename)
    return UserMessage(content=parts)


class ContextBuilder:
    def __init__(self, config: "ContextConfig", hook_registry: "Optional[HookRegistry]" = None) -> None:
        self.config = config
        self._hook_registry = hook_registry

    def build_system_prompt(self, ctx: HookContext) -> str:
        return self.build_system_prompt_layers(ctx).render()

    def build_system_prompt_layers(self, ctx: HookContext) -> SystemPromptLayers:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        layers = SystemPromptLayers()

        if self.config.soul_content:
            layers.identity.append(self.config.soul_content)
        else:
            template = self.config.system_prompt_template
            layers.identity.append(
                template.format(
                    now=now,
                    user_id=ctx.request.sender.user_id,
                    display_name=ctx.request.sender.display_name,
                    source=ctx.request.source,
                )
            )

        relationship = ctx.metadata.get("relationship", "")
        if relationship:
            layers.identity.append(f"## 與當前對話者的關係\n{relationship}")

        if self._hook_registry is not None:
            for hook in self._hook_registry.hooks:
                hook.contribute_prompt(ctx, layers)

        layers.identity.append(
            f"當前對話者: {ctx.request.sender.display_name} ({ctx.request.sender.user_id})\n當前時間: {now}"
        )

        return layers

    def build_context_manager(self, ctx: HookContext) -> ContextManager:
        config = self.config

        async def transform(messages: List[AppMessage]) -> List[AppMessage]:
            if config.history_strategy == "full":
                return messages

            max_msgs = config.max_history_messages
            msgs = messages[-max_msgs:] if len(messages) > max_msgs else list(messages)
            # TODO: 需處理真實TOKRN計算
            if config.context_token_budget is not None:
                threshold = int(config.context_token_budget * config.compact_threshold)
                if _estimate_tokens(msgs) > threshold:
                    before_len = len(msgs)
                    msgs = await _compact_messages(msgs)
                    logger.warning(
                        "Context budget exceeded (threshold={}): compacted from {} to {} messages",
                        threshold,
                        before_len,
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
