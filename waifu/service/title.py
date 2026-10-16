import asyncio
from typing import TYPE_CHECKING, Dict, Set

from waifu.logger import logger
from waifu_types import Event, IncomingRequest, RequestMeta

if TYPE_CHECKING:
    from waifu.agent.utilai import UtilityAI
    from waifu.store.conversation import ConversationStore


class AutoTitleService:
    MAX_ATTEMPTS = 3

    def __init__(self, store: "ConversationStore", utility_ai: "UtilityAI") -> None:
        self._store = store
        self._utility_ai = utility_ai
        self._inflight: Set[str] = set()
        self._attempts: Dict[str, int] = {}
        self._tasks: Set["asyncio.Task[None]"] = set()  # 保留引用，避免背景工作被 GC

    def schedule(self, request: IncomingRequest, assistant_reply: str) -> None:
        cid = request.conversation_id
        if not assistant_reply or request.metadata.get(RequestMeta.SKIP_AUTO_TITLE) or cid in self._inflight:
            return
        if self._attempts.get(cid, 0) >= self.MAX_ATTEMPTS or not self._store.needs_auto_title(cid):
            return
        self._inflight.add(cid)
        task = asyncio.create_task(self._run(request, assistant_reply))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def wait_idle(self) -> None:
        """等待所有命名工作完成（測試 / 關閉時使用）"""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _run(self, request: IncomingRequest, assistant_reply: str) -> None:
        cid = request.conversation_id
        try:
            self._attempts[cid] = self._attempts.get(cid, 0) + 1
            title = await self._utility_ai.generate_title(request.content, assistant_reply)
            if not title or not self._store.set_auto_title(cid, title):
                return
            self._attempts.pop(cid, None)
            logger.info("Auto-titled conversation {} → '{}'", cid[:8], title)
            try:
                await request.reply_event(Event(event="title_update", data={"conversation_id": cid, "title": title}))
            except Exception:
                logger.debug("title_update event could not be delivered (connection closed?)")
        except Exception:
            logger.exception("Auto title failed for conversation {}", cid)
        finally:
            self._inflight.discard(cid)
