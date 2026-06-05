import inspect
from typing import Dict, List, Optional, Protocol, runtime_checkable

from waifu_types import BaseHook, BaseMessage, ConversationMode, HookContext


@runtime_checkable
class MemoryStore(Protocol):
    async def load(self, key: str) -> List[BaseMessage]: ...
    async def save(self, key: str, messages: List[BaseMessage]) -> None: ...


@runtime_checkable
class ContextualMemoryStore(MemoryStore, Protocol):
    async def load_for_context(self, ctx: HookContext, key: str) -> List[BaseMessage]: ...
    async def save_for_context(self, ctx: HookContext, key: str, messages: List[BaseMessage]) -> None: ...


@runtime_checkable
class RelationshipMemoryStore(MemoryStore, Protocol):
    async def get_relationship(self, key: str) -> str: ...


class MemoryHook(BaseHook):
    """
    對話歷史持久化 Hook

    pre ：從外部 store 載入歷史，注入 ctx.messages；若 store 支援關係層，注入 ctx.metadata
    post：將本輪新訊息寫回 store

    store 介面（duck typing）：
        async def load(key: str) -> List[Dict]
        async def save(key: str, messages: List[Dict]) -> None
        async def get_relationship(key: str) -> str  (optional)

    預設使用內建的 InMemoryStore（無持久化，重啟清空）
    傳入 FileMemoryStore / Redis / SQLite store 即可替換
    """

    name = "memory"
    priority = 10

    def __init__(self, store: Optional[MemoryStore] = None, max_history: int = 50) -> None:
        self._store = store or InMemoryStore()
        self._max_history = max_history

    async def pre(self, ctx: HookContext) -> HookContext:
        cid = ctx.request.conversation_id
        history = await self._load_history(ctx, cid)
        if history:
            ctx.messages = list(history)

        if isinstance(self._store, RelationshipMemoryStore):
            await self._inject_relationship(ctx, self._store)

        return ctx

    async def post(self, ctx: HookContext) -> HookContext:
        if ctx.response is None:
            return ctx

        cid = ctx.request.conversation_id
        full_history = list(ctx.session.history)

        if len(full_history) > self._max_history:
            full_history = full_history[-self._max_history :]

        await self._save_history(ctx, cid, full_history)
        return ctx

    async def clear(self, conversation_id: str) -> None:
        clear_fn = getattr(self._store, "clear", None)
        if clear_fn is None:
            return
        result = clear_fn(conversation_id)
        if inspect.isawaitable(result):
            await result

    async def _inject_relationship(self, ctx: HookContext, store: RelationshipMemoryStore) -> None:
        """從 store 取得關係層，注入 ctx.metadata["relationship"]"""
        if ctx.request.mode == ConversationMode.session:
            return

        direct_key = f"{ctx.request.source}:dm:{ctx.request.sender.user_id}"
        relationship = await store.get_relationship(direct_key)
        if relationship:
            ctx.metadata["relationship"] = relationship

    async def _load_history(self, ctx: HookContext, key: str) -> List[BaseMessage]:
        if isinstance(self._store, ContextualMemoryStore):
            return await self._store.load_for_context(ctx, key)
        return await self._store.load(key)

    async def _save_history(self, ctx: HookContext, key: str, messages: List[BaseMessage]) -> None:
        if isinstance(self._store, ContextualMemoryStore):
            await self._store.save_for_context(ctx, key, messages)
            return
        await self._store.save(key, messages)


class InMemoryStore:
    """簡易 in-memory 歷史 store（預設，重啟清空）"""

    def __init__(self) -> None:
        self._data: Dict[str, List[BaseMessage]] = {}

    async def load(self, key: str) -> List[BaseMessage]:
        return list(self._data.get(key, []))

    async def save(self, key: str, messages: List[BaseMessage]) -> None:
        self._data[key] = list(messages)

    async def clear(self, key: str) -> None:
        self._data.pop(key, None)


__all__ = [
    "ContextualMemoryStore",
    "InMemoryStore",
    "MemoryHook",
    "MemoryStore",
    "RelationshipMemoryStore",
]
