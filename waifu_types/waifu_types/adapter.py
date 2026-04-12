from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from .types import OutgoingResponse

if TYPE_CHECKING:
    from waifu.gateway.core import GatewayCore


class BaseGatewayAdapter(ABC):
    name: str

    @abstractmethod
    async def start(self, core: "GatewayCore") -> None:
        """掛載到 GatewayCore，開始監聽事件"""
        ...

    @abstractmethod
    async def send(self, response: OutgoingResponse) -> None:
        """將 OutgoingResponse 傳送回對應的平台"""
        ...
