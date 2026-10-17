from typing import Any, Dict, Optional, Protocol

from waifu_types.command import CommandCatalog
from waifu_types.services import SessionService
from waifu_types.types import IncomingRequest, OutgoingResponse


class GatewayProtocol(Protocol):
    """Adapter 在 start() 時拿到的 gateway 介面"""

    @property
    def session_manager(self) -> SessionService: ...

    @property
    def command_service(self) -> Optional[CommandCatalog]: ...

    @property
    def capabilities(self) -> Dict[str, Any]: ...

    async def dispatch(self, request: IncomingRequest) -> None:
        """排入該對話的 Lane"""
        ...

    async def dispatch_and_wait(self, request: IncomingRequest) -> OutgoingResponse:
        """同 dispatch，但等待並回傳最終回應"""
        ...

    async def interrupt(self, conversation_id: str) -> Optional[IncomingRequest]:
        """中斷該對話正在處理的請求，回傳被中斷的請求；沒有進行中的請求時為 None"""
        ...
