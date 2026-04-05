import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from waifu_types import BaseHook, BasePlugin, PluginContext

logger = logging.getLogger(__name__)


class PluginState(str, Enum):
    loading = "loading"
    enabled = "enabled"
    disabled = "disabled"
    error = "error"


class PluginRegistry:
    """
    統一管理所有從插件注冊的 Tool、Hook、MCP Adapter。

    PluginManager 透過 _PluginContextImpl 注入此 registry，
    各插件在 on_load() 中呼叫 ctx.register_* 來填充。
    """

    def __init__(self) -> None:
        self._tools: List[Any] = []  # hai.tool.Tool
        self._hooks: List[BaseHook] = []
        self._mcp_adapters: Dict[str, Any] = {}  # name → BaseMCPAdapter

    def add_tool(self, tool: Any) -> None:
        self._tools.append(tool)

    def add_hook(self, hook: BaseHook) -> None:
        self._hooks.append(hook)

    def add_mcp(self, name: str, adapter: Any) -> None:
        self._mcp_adapters[name] = adapter

    def get_all_tools(self) -> List[Any]:
        return list(self._tools)

    def get_all_hooks(self) -> List[BaseHook]:
        return list(self._hooks)

    def get_mcp(self, name: str) -> Optional[Any]:
        return self._mcp_adapters.get(name)


class _PluginContextImpl:
    """PluginContext 的具體實作，注入給插件的 on_load()。"""

    def __init__(
        self,
        registry: PluginRegistry,
        hook_registry: Any,  # waifu.hook.HookRegistry
        config: Dict[str, Any],
    ) -> None:
        self._registry = registry
        self._hook_registry = hook_registry
        self.config = config

    def register_hook(self, hook: BaseHook) -> None:
        self._registry.add_hook(hook)
        self._hook_registry.register(hook)

    def register_tool(self, tool: Any) -> None:
        self._registry.add_tool(tool)

    def register_mcp(self, name: str, adapter: Any) -> None:
        self._registry.add_mcp(name, adapter)


class PluginManager:
    """
    插件生命週期管理：load / enable / disable / unload。

    使用 DI：HookRegistry 由外部注入，PluginManager 不直接依賴具體實作。
    """

    def __init__(self, hook_registry: Any, plugin_registry: PluginRegistry) -> None:
        self._hook_registry = hook_registry
        self._plugin_registry = plugin_registry
        self._plugins: Dict[str, Tuple[BasePlugin, PluginState]] = {}

    async def load(self, plugin: BasePlugin, config: Optional[Dict[str, Any]] = None) -> None:
        name = plugin.name
        self._plugins[name] = (plugin, PluginState.loading)
        try:
            ctx = _PluginContextImpl(
                registry=self._plugin_registry,
                hook_registry=self._hook_registry,
                config=config or {},
            )
            await plugin.on_load(ctx)
            await plugin.on_enable()
            self._plugins[name] = (plugin, PluginState.enabled)
            logger.info("Plugin loaded: %s v%s", name, plugin.version)
        except Exception:
            self._plugins[name] = (plugin, PluginState.error)
            logger.exception("Plugin load error: %s", name)
            raise

    async def unload(self, name: str) -> None:
        plugin, _ = self._plugins[name]
        await plugin.on_disable()
        await plugin.on_unload()
        del self._plugins[name]
        logger.info("Plugin unloaded: %s", name)

    async def enable(self, name: str) -> None:
        plugin, _ = self._plugins[name]
        await plugin.on_enable()
        self._plugins[name] = (plugin, PluginState.enabled)

    async def disable(self, name: str) -> None:
        plugin, _ = self._plugins[name]
        await plugin.on_disable()
        self._plugins[name] = (plugin, PluginState.disabled)

    def list(self) -> List[Dict[str, Any]]:
        return [
            {"name": n, "state": s.value, "version": p.version, "description": p.description}
            for n, (p, s) in self._plugins.items()
        ]


__all__ = ["PluginManager", "PluginRegistry", "PluginState"]
