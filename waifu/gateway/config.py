from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import yaml
from pydantic import BaseModel, Field

from waifu_types import BaseGatewayAdapter


class GatewayAdapterStatus(BaseModel):
    name: str
    enabled: bool
    configured: bool = True
    registered: bool = True


class GatewayRuntimeConfig(BaseModel):
    adapters: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "GatewayRuntimeConfig":
        if not path.exists():
            return cls()
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.model_validate(data)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.model_dump(mode="python")
        path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def deep_merge_dict(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = deep_merge_dict(current, value)
        else:
            merged[key] = value
    return merged


class GatewayAdapterRegistry:
    def __init__(self) -> None:
        self._adapter_types: Dict[str, type[BaseGatewayAdapter]] = {}

    def register(self, adapter_type: type[BaseGatewayAdapter]) -> None:
        self._adapter_types[adapter_type.name] = adapter_type

    def remove(self, name: str) -> None:
        self._adapter_types.pop(name, None)

    def list_names(self) -> List[str]:
        return list(self._adapter_types)

    def normalize(self, config: GatewayRuntimeConfig) -> GatewayRuntimeConfig:
        adapters = dict(config.adapters)
        for name, adapter_type in self._adapter_types.items():
            current = adapters.get(name, {})
            adapters[name] = deep_merge_dict(adapter_type.default_gateway_config(), current)
        return GatewayRuntimeConfig(adapters=adapters)

    def create_default_config(self) -> GatewayRuntimeConfig:
        return self.normalize(GatewayRuntimeConfig())

    def get_adapter_config(self, config: GatewayRuntimeConfig, name: str) -> Dict[str, Any]:
        normalized = self.normalize(config)
        return dict(normalized.adapters.get(name, {}))

    def build_status(self, config: GatewayRuntimeConfig) -> List[GatewayAdapterStatus]:
        normalized = self.normalize(config)
        items: List[GatewayAdapterStatus] = []

        for name, adapter_type in self._adapter_types.items():
            raw = adapter_type.build_gateway_status(normalized.adapters.get(name, {}))
            items.append(GatewayAdapterStatus.model_validate(raw))

        for name, adapter_config in normalized.adapters.items():
            if name in self._adapter_types:
                continue
            items.append(
                GatewayAdapterStatus(
                    name=name,
                    enabled=bool(adapter_config.get("enabled", False)),
                    configured=True,
                    registered=False,
                )
            )

        return items

    def build_runtime_adapters(self, config: GatewayRuntimeConfig, **deps: Any) -> List[BaseGatewayAdapter]:
        normalized = self.normalize(config)
        adapters: List[BaseGatewayAdapter] = []
        for name, adapter_type in self._adapter_types.items():
            adapter = adapter_type.from_gateway_config(normalized.adapters.get(name, {}), **deps)
            if adapter is not None:
                adapters.append(adapter)
        return adapters


def build_builtin_gateway_adapter_registry() -> GatewayAdapterRegistry:
    from waifu.gateway.adapters import DiscordAdapter, HTTPAdapter, TelegramAdapter, WebSocketAdapter

    registry = GatewayAdapterRegistry()
    for adapter_type in (WebSocketAdapter, HTTPAdapter, DiscordAdapter, TelegramAdapter):
        registry.register(adapter_type)
    return registry
