from typing import Dict, List

from waifu.plugin import PluginManager
from waifu.plugin.loader import PluginLoader, PluginMeta
from waifu.store.models import PluginConfig
from waifu.store.repositories.plugin import PluginRepository


class PluginService:
    def __init__(self, repo: PluginRepository, plugin_manager: PluginManager, loader: PluginLoader) -> None:
        self._repo = repo
        self._pm = plugin_manager
        self._loader = loader

    async def install(self, plugin_name: str, config: dict) -> PluginConfig:
        plugin = self._loader.resolve(plugin_name)
        await self._pm.load(plugin, config)
        return self._repo.create(plugin.name, plugin_name, config)

    async def uninstall(self, name: str) -> None:
        await self._pm.unload(name)
        self._repo.delete(name)

    async def enable(self, name: str) -> None:
        await self._pm.enable(name)
        self._repo.set_enabled(name, True)

    async def disable(self, name: str) -> None:
        await self._pm.disable(name)
        self._repo.set_enabled(name, False)

    def list_installed(self) -> List[Dict]:
        return self._pm.list()

    def list_available(self) -> List[PluginMeta]:
        return self._loader.list_available()
