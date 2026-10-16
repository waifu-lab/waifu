import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional

from waifu.logger import logger
from waifu_types import BaseGatewayAdapter, CommandCatalog, IncomingRequest, OutgoingResponse

from .lane import LaneManager
from .session import SessionManager

_DispatchHandler = Callable[[IncomingRequest], Awaitable[OutgoingResponse]]


class GatewayCore:
    """實作 waifu_types.GatewayProtocol"""

    def __init__(self, session_ttl: int = 3600, lane_max_queue: int = 10):
        self._adapters: List[BaseGatewayAdapter] = []
        self._session_manager = SessionManager(ttl=session_ttl)
        self._lane_manager = LaneManager(max_queue_size=lane_max_queue)
        self._dispatch_handler: Optional[_DispatchHandler] = None
        self._command_service: Optional[CommandCatalog] = None
        self._started: bool = False
        self._capabilities: Dict[str, Any] = {}

    def mount(self, adapter: BaseGatewayAdapter) -> "GatewayCore":
        self._adapters.append(adapter)
        return self

    async def mount_adapter(self, adapter: BaseGatewayAdapter) -> None:
        self._adapters.append(adapter)
        if self._started:
            await adapter.start(self)

    def set_dispatch_handler(self, handler: _DispatchHandler) -> None:
        """注入請求處理器（由 Waifu 在組裝時呼叫）"""
        self._dispatch_handler = handler

    def set_command_service(self, service: CommandCatalog) -> None:
        """注入平台內建指令服務，供 adapters 註冊 native commands。"""
        self._command_service = service

    @property
    def command_service(self) -> Optional[CommandCatalog]:
        return self._command_service

    @property
    def capabilities(self) -> Dict[str, Any]:
        return self._capabilities

    async def dispatch(self, request: IncomingRequest) -> None:
        """將請求放入對應 conversation 的 Lane，確保串行執行；結果透過 reply_fn 回傳"""
        fut = await self._enqueue(request)
        fut.add_done_callback(_consume_result)

    async def dispatch_and_wait(self, request: IncomingRequest) -> OutgoingResponse:
        """同 dispatch，但等待並回傳最終回應（cron / heartbeat / SDK 使用）"""
        return await (await self._enqueue(request))

    async def _enqueue(self, request: IncomingRequest) -> "asyncio.Future[OutgoingResponse]":
        lane = self._lane_manager.get_or_create(request.conversation_id)
        return await lane.enqueue(request, self._handle_request)

    async def start(self) -> None:
        """啟動所有掛載的 Adapter"""
        self._started = True
        await asyncio.gather(*[adapter.start(self) for adapter in self._adapters])

    async def stop(self) -> None:
        self._started = False
        for adapter in self._adapters:
            try:
                await adapter.stop()
            except Exception:
                logger.exception("GatewayCore: error stopping adapter {}", adapter.name)

    @property
    def session_manager(self) -> SessionManager:
        return self._session_manager

    @property
    def adapters(self) -> List[BaseGatewayAdapter]:
        return list(self._adapters)

    async def _handle_request(self, request: IncomingRequest) -> OutgoingResponse:
        if self._dispatch_handler is None:
            raise RuntimeError(f"GatewayCore: no dispatch_handler set, dropping request {request.request_id}")
        response = await self._dispatch_handler(request)
        try:
            await request.reply(response)
        except Exception:
            logger.exception("GatewayCore: failed to deliver response for request {}", request.request_id)
        return response


def _consume_result(fut: "asyncio.Future[OutgoingResponse]") -> None:
    # 錯誤已由 Lane 記錄；取出 exception 避免 "exception was never retrieved"
    if not fut.cancelled():
        fut.exception()
