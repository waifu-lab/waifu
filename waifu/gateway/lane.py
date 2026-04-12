import asyncio
import logging
from typing import Awaitable, Callable, Dict, Tuple

from waifu_types import IncomingRequest

logger = logging.getLogger(__name__)

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
        while not self._queue.empty():
            item, handler = self._queue.get_nowait()
            try:
                await handler(item)
            except Exception as e:
                logger.exception("Lane handler error: %s", e)
            finally:
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
