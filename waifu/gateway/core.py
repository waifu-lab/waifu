import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional

from waifu_types import BaseGatewayAdapter, IncomingRequest, OutgoingResponse

from .lane import LaneManager
from .session import SessionManager

from waifu.logger import logger


class GatewayCore:
    """
    系統唯一入口：管理 Adapter、Session、LaneQueue

    使用 DI：dispatch_handler 由外部（Waifu 主類）注入，
    讓 GatewayCore 不直接依賴 Agent 或 Hook 邏輯
    """

    def __init__(self, session_ttl: int = 3600, lane_max_queue: int = 10):
        self._adapters: List[BaseGatewayAdapter] = []
        self._session_manager = SessionManager(ttl=session_ttl)
        self._lane_manager = LaneManager(max_queue_size=lane_max_queue)
        self._dispatch_handler: Optional[Callable[[IncomingRequest], Awaitable[OutgoingResponse]]] = None
        self._started: bool = False
        self.capabilities: Dict[str, Any] = {}

    def mount(self, adapter: BaseGatewayAdapter) -> "GatewayCore":
        self._adapters.append(adapter)
        return self

    async def mount_adapter(self, adapter: BaseGatewayAdapter) -> None:
        """掛載 adapter；若 gateway 已啟動則立即 start，否則等 start() 時一併啟動"""
        self._adapters.append(adapter)
        if self._started:
            await adapter.start(self)

    def set_dispatch_handler(
        self,
        handler: Callable[[IncomingRequest], Awaitable[OutgoingResponse]],
    ) -> None:
        """注入請求處理器（由 Waifu 在組裝時呼叫）"""
        self._dispatch_handler = handler

    async def dispatch(self, request: IncomingRequest) -> None:
        """將請求放入對應 conversation 的 Lane，確保串行執行"""
        lane = self._lane_manager.get_or_create(request.conversation_id)
        await lane.enqueue(request, self._handle_request)

    async def start(self) -> None:
        """啟動所有掛載的 Adapter"""
        self._started = True
        await asyncio.gather(*[adapter.start(self) for adapter in self._adapters])

    @property
    def session_manager(self) -> SessionManager:
        return self._session_manager

    @property
    def adapters(self) -> List[BaseGatewayAdapter]:
        return list(self._adapters)

    async def _handle_request(self, request: IncomingRequest) -> None:
        if self._dispatch_handler is None:
            logger.warning("GatewayCore: no dispatch_handler set, dropping request {}", request.request_id)
            return
        try:
            response = await self._dispatch_handler(request)
            await request.reply_fn(response)
        except Exception:
            logger.exception("GatewayCore: error handling request {}", request.request_id)
