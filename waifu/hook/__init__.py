from typing import List

from waifu.logger import logger
from waifu_types import BaseHook, HookContext


class HookRegistry:
    """管理所有 Hook 的注冊與排序"""

    def __init__(self) -> None:
        self._hooks: List[BaseHook] = []

    def register(self, hook: BaseHook) -> None:
        self._hooks.append(hook)
        self._hooks.sort(key=lambda h: h.priority)

    def unregister(self, name: str) -> None:
        self._hooks = [h for h in self._hooks if h.name != name]

    @property
    def hooks(self) -> List[BaseHook]:
        return list(self._hooks)


class HookPipeline:
    """依序執行 HookRegistry 中所有 Hook 的 pre/post"""

    def __init__(self, registry: HookRegistry) -> None:
        self._registry = registry

    async def run_pre(self, ctx: HookContext) -> HookContext:
        for hook in self._registry.hooks:
            if ctx.abort:
                break
            try:
                ctx = await hook.pre(ctx)
            except Exception:
                logger.exception("Hook {} pre() error", hook.name)
        return ctx

    async def run_mid(self, ctx: HookContext) -> HookContext:
        for hook in self._registry.hooks:
            try:
                ctx = await hook.mid(ctx)
            except Exception:
                logger.exception("Hook {} mid() error", hook.name)
        return ctx

    async def run_post(self, ctx: HookContext) -> HookContext:
        for hook in self._registry.hooks:
            try:
                ctx = await hook.post(ctx)
            except Exception:
                logger.exception("Hook {} post() error", hook.name)
        return ctx


from .builtin import EmotionHook, LoggingHook, RateLimitHook, TTSHook
from .memory import (
    ContextualMemoryStore,
    InMemoryStore,
    MemoryHook,
    MemoryStore,
    RelationshipMemoryStore,
)

__all__ = [
    "HookRegistry",
    "HookPipeline",
    "RateLimitHook",
    "MemoryStore",
    "ContextualMemoryStore",
    "RelationshipMemoryStore",
    "MemoryHook",
    "InMemoryStore",
    "EmotionHook",
    "LoggingHook",
    "TTSHook",
]
