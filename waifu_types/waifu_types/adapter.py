from abc import ABC, abstractmethod
from typing import Any, Dict, List

from .gateway import GatewayProtocol
from .services import ServiceProvider
from .types import OutgoingResponse


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

    def on_mount(self, services: ServiceProvider) -> None:  # noqa: B027
        ...

    def routers(self) -> List[Any]:

        return []

    @abstractmethod
    async def start(self, core: GatewayProtocol) -> None: ...

    async def stop(self) -> None:  # noqa: B027
        ...

    async def send(self, response: OutgoingResponse) -> None:

        raise NotImplementedError(f"adapter {self.name!r} does not support proactive send")
