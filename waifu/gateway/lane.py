import asyncio
from typing import Awaitable, Callable, Dict, Optional, Tuple

from waifu_types import IncomingRequest, OutgoingResponse

from waifu.logger import logger

_Handler = Callable[[IncomingRequest], Awaitable[OutgoingResponse]]
_Item = Tuple[IncomingRequest, _Handler, "asyncio.Future[OutgoingResponse]"]


class Lane:
    """Per-conversation serial processing queue — 確保同一對話空間串行處理"""

    def __init__(self, max_size: int = 10, on_idle: Optional[Callable[["Lane"], None]] = None):
        self._queue: asyncio.Queue[_Item] = asyncio.Queue(maxsize=max_size)
        self._task: asyncio.Task | None = None
        self._on_idle = on_idle
        self._pending = 0  # 已呼叫 enqueue 但尚未處理完的請求數（含等待 put 中的）
        self._current: Optional[Tuple[IncomingRequest, "asyncio.Task[OutgoingResponse]"]] = None
        self._interrupted: Optional["asyncio.Task[OutgoingResponse]"] = None

    @property
    def idle(self) -> bool:
        return self._pending == 0

    async def interrupt(self) -> Optional[IncomingRequest]:
        """取消正在處理的請求（佇列中的不受影響），等它收尾完成後回傳該請求；沒有進行中的請求時回傳 None"""
        if self._current is None:
            return None
        request, task = self._current
        self._interrupted = task
        task.cancel()
        await asyncio.wait([task])
        return request

    async def enqueue(self, item: IncomingRequest, handler: _Handler) -> "asyncio.Future[OutgoingResponse]":
        """排入佇列並回傳完成時的 Future；佇列已滿時會等待空位"""
        fut: asyncio.Future[OutgoingResponse] = asyncio.get_running_loop().create_future()
        self._pending += 1
        try:
            await self._queue.put((item, handler, fut))
        except BaseException:
            self._pending -= 1
            raise
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._drain())
        return fut

    async def _drain(self) -> None:
        from waifu.logger import cid

        while not self._queue.empty():
            item, handler, fut = self._queue.get_nowait()
            token = cid.set(item.conversation_id)

            task = asyncio.create_task(handler(item))
            self._current = (item, task)
            try:
                result = await task
                if not fut.done():
                    fut.set_result(result)
            except asyncio.CancelledError:
                if not fut.done():
                    fut.cancel()
                if self._interrupted is not task:
                    raise
            except Exception as e:
                logger.exception("Lane handler error: {}", e)
                if not fut.done():
                    fut.set_exception(e)
            finally:
                self._current = None
                self._interrupted = None
                cid.reset(token)
                self._queue.task_done()
                self._pending -= 1

        if self._pending == 0 and self._on_idle is not None:
            self._on_idle(self)


class LaneManager:
    """管理每個 conversation_id 對應的 Lane 實例；Lane 閒置後自動移除"""

    def __init__(self, max_queue_size: int = 10):
        self._lanes: Dict[str, Lane] = {}
        self._max_queue_size = max_queue_size

    def get_or_create(self, conversation_id: str) -> Lane:
        lane = self._lanes.get(conversation_id)
        if lane is None:
            lane = Lane(self._max_queue_size, on_idle=lambda done: self._release(conversation_id, done))
            self._lanes[conversation_id] = lane
        return lane

    async def interrupt(self, conversation_id: str) -> Optional[IncomingRequest]:
        lane = self._lanes.get(conversation_id)
        return await lane.interrupt() if lane is not None else None

    def _release(self, conversation_id: str, lane: Lane) -> None:
        if self._lanes.get(conversation_id) is lane and lane.idle:
            del self._lanes[conversation_id]

    def __len__(self) -> int:
        return len(self._lanes)
