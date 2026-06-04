from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict

from .types import OutgoingResponse

if TYPE_CHECKING:
    pass


class BaseGatewayAdapter(ABC):
    name: str

    @classmethod
    def default_gateway_config(cls) -> Dict[str, Any]:
        return {"enabled": False}

    @classmethod
    def build_gateway_status(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": cls.name,
            "enabled": bool(config.get("enabled", False)),
            "configured": True,
        }

    @classmethod
    def from_gateway_config(cls, config: Dict[str, Any], **deps: Any) -> "BaseGatewayAdapter | None":
        del config, deps
        return None

    @abstractmethod
    async def start(self, core: Any) -> None:
        """掛載到 GatewayCore，開始監聽事件"""
        ...

    @abstractmethod
    async def send(self, response: OutgoingResponse) -> None:
        """將 OutgoingResponse 傳送回對應的平台"""
        ...
