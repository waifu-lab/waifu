import asyncio
from typing import Awaitable, Callable, Dict, Tuple

from waifu_types import IncomingRequest

from waifu.logger import logger

_Handler = Callable[[IncomingRequest], Awaitable[None]]


class Lane:
    """Per-conversation serial processing queue — 確保同一對話空間串行處理"""

    def __init__(self, max_size: int = 10):
        self._queue: asyncio.Queue[Tuple[IncomingRequest, _Handler]] = asyncio.Queue(maxsize=max_size)
        self._task: asyncio.Task | None = None

    async def enqueue(self, item: IncomingRequest, handler: _Handler) -> None:
        await self._queue.put((item, handler))
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._drain())

    async def _drain(self) -> None:
        from waifu.logger import cid

        while not self._queue.empty():
            item, handler = self._queue.get_nowait()
            token = cid.set(item.conversation_id)
            try:
                await handler(item)
            except Exception as e:
                logger.exception("Lane handler error: {}", e)
            finally:
                cid.reset(token)
                self._queue.task_done()


class LaneManager:
    """管理每個 conversation_id 對應的 Lane 實例"""

    def __init__(self, max_queue_size: int = 10):
        self._lanes: Dict[str, Lane] = {}
        self._max_queue_size = max_queue_size

    def get_or_create(self, conversation_id: str) -> Lane:
        if conversation_id not in self._lanes:
            self._lanes[conversation_id] = Lane(self._max_queue_size)
        return self._lanes[conversation_id]
