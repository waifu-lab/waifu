from typing import Any, Dict, List, Tuple, Union

from waifu.logger import logger
from waifu_types import BaseHook, HookContext, OutputTransformer, StreamObserver

from .builtin import EmotionHook, LoggingHook, RateLimitHook, TTSHook
from .memory import (
    ContextualMemoryStore,
    InMemoryStore,
    MemoryHook,
    MemoryStore,
    RelationshipMemoryStore,
)


class HookRegistry:
    """管理所有 Hook 的注冊與排序"""

    def __init__(self) -> None:
        self._hooks: List[BaseHook] = []

    def register(self, hook: BaseHook) -> None:
        if any(h.name == hook.name for h in self._hooks):
            logger.warning("Hook name {!r} registered more than once", hook.name)
        self._hooks.append(hook)
        self._hooks.sort(key=lambda h: h.priority)

    def unregister(self, hook: Union[BaseHook, str]) -> None:
        """傳入 hook 實例只移除該實例；傳入名稱則移除所有同名 hook"""
        if isinstance(hook, str):
            self._hooks = [h for h in self._hooks if h.name != hook]
        else:
            self._hooks = [h for h in self._hooks if h is not hook]

    @property
    def hooks(self) -> List[BaseHook]:
        return list(self._hooks)

    def output_transformers(self) -> List[OutputTransformer]:
        return [t for h in self._hooks for t in h.output_transformers()]

    def capabilities(self) -> Dict[str, Any]:
        caps: Dict[str, Any] = {}
        for hook in self._hooks:
            caps.update(hook.capabilities())
        return caps


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

    def stream_observer(self, ctx: HookContext) -> StreamObserver:
        observers: List[Tuple[str, StreamObserver]] = []
        for hook in self._registry.hooks:
            try:
                observer = hook.stream_observer(ctx)
            except Exception:
                logger.exception("Hook {} stream_observer() error", hook.name)
                continue
            if observer is not None:
                observers.append((hook.name, observer))
        return _ChainedObserver(observers)


class _ChainedObserver(StreamObserver):
    def __init__(self, observers: List[Tuple[str, StreamObserver]]) -> None:
        self._observers = observers

    def feed(self, chunk: str) -> None:
        self._each("feed", chunk)

    def end_turn(self) -> None:
        self._each("end_turn")

    def reset(self) -> None:
        self._each("reset")

    async def finish(self) -> None:
        await self._each_async("finish")

    async def aclose(self) -> None:
        await self._each_async("aclose")

    def _each(self, method: str, *args: Any) -> None:
        for name, observer in self._observers:
            try:
                getattr(observer, method)(*args)
            except Exception:
                logger.exception("Hook {} stream observer {}() error", name, method)

    async def _each_async(self, method: str) -> None:
        for name, observer in self._observers:
            try:
                await getattr(observer, method)()
            except Exception:
                logger.exception("Hook {} stream observer {}() error", name, method)


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
