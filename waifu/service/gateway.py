from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from waifu.gateway.config import (
    GatewayAdapterRegistry,
    GatewayRuntimeConfig,
    build_builtin_gateway_adapter_registry,
    deep_merge_dict,
)
from waifu_types import BaseGatewayAdapter


class GatewayConfigService:
    def __init__(
        self,
        path: Path,
        config: GatewayRuntimeConfig,
        adapter_registry: GatewayAdapterRegistry | None = None,
    ) -> None:
        self._path = path
        self._registry = adapter_registry or build_builtin_gateway_adapter_registry()
        self._config = self._registry.normalize(config)
        self.ensure_initialized()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def adapter_registry(self) -> GatewayAdapterRegistry:
        return self._registry

    def ensure_initialized(self) -> None:
        normalized = self._registry.normalize(self._config)
        should_write = not self._path.exists() or normalized.model_dump(mode="python") != self._config.model_dump(
            mode="python"
        )
        self._config = normalized
        if should_write:
            self._config.save(self._path)

    def get_config(self) -> Dict[str, Any]:
        self.ensure_initialized()
        return self._config.model_dump(mode="python")

    def get_adapter_config(self, name: str) -> Dict[str, Any]:
        self.ensure_initialized()
        return self._registry.get_adapter_config(self._config, name)

    def update_config(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        merged = deep_merge_dict(self.get_config(), patch)
        self._config = self._registry.normalize(GatewayRuntimeConfig.model_validate(merged))
        self._config.save(self._path)
        return {
            "status": "saved",
            "note": "requires restart",
            "path": str(self._path),
            "config": self.get_config(),
        }

    def get_adapter_status(self) -> List[Dict[str, Any]]:
        self.ensure_initialized()
        return [item.model_dump(mode="python") for item in self._registry.build_status(self._config)]

    def build_runtime_adapters(self, **deps: Any) -> List[BaseGatewayAdapter]:
        self.ensure_initialized()
        return self._registry.build_runtime_adapters(self._config, **deps)

    def register_adapter_type(self, adapter_type: type[BaseGatewayAdapter]) -> None:
        self._registry.register(adapter_type)
        self.ensure_initialized()

    def remove_adapter_type(self, name: str) -> None:
        self._registry.remove(name)
