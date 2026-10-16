from typing import Any, Dict, Optional, Type, TypeVar

T = TypeVar("T")


class ServiceRegistry:
    def __init__(self) -> None:
        self._services: Dict[type, Any] = {}

    def register(self, key: Type[T], service: T) -> None:
        self._services[key] = service

    def get(self, key: Type[T]) -> Optional[T]:
        return self._services.get(key)
