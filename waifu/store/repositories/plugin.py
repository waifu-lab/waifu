import json
from typing import List, Optional

from waifu.store.models import PluginConfig


class PluginRepository:
    def create(self, name: str, plugin_name: str, config: dict) -> PluginConfig:
        return PluginConfig.create(
            name=name,
            plugin_name=plugin_name,
            config_json=json.dumps(config),
        )

    def delete(self, name: str) -> None:
        PluginConfig.delete().where(PluginConfig.name == name).execute()

    def set_enabled(self, name: str, enabled: bool) -> None:
        PluginConfig.update(enabled=enabled).where(PluginConfig.name == name).execute()

    def update_config(self, name: str, config: dict) -> None:
        PluginConfig.update(config_json=json.dumps(config)).where(PluginConfig.name == name).execute()

    def get(self, name: str) -> Optional[PluginConfig]:
        return PluginConfig.get_or_none(PluginConfig.name == name)

    def list_enabled(self) -> List[PluginConfig]:
        return list(PluginConfig.select().where(PluginConfig.enabled == True))  # noqa: E712

    def list_all(self) -> List[PluginConfig]:
        return list(PluginConfig.select())
