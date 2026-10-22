from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from hai.tool import Tool

from waifu_types import (
    BaseGatewayAdapter,
    BaseHook,
    BaseMCPAdapter,
    BasePlugin,
    CommandDefinition,
    CommandHandler,
    ConversationService,
    SessionService,
    ToolLike,
    VoiceServiceProtocol,
)

if TYPE_CHECKING:
    from waifu.gateway.core import GatewayCore
    from waifu.hook import HookRegistry
    from waifu.mcp.manager import MCPManager
    from waifu.service.command import CommandService
    from waifu.service.gateway import GatewayConfigService

from waifu.logger import logger


class PluginState(str, Enum):
    loading = "loading"
    enabled = "enabled"
    disabled = "disabled"
    error = "error"


def as_hai_tool(tool: ToolLike) -> Tool:
    if isinstance(tool, Tool):
        return tool
    return Tool(name=tool.name, description=tool.description, parameters=tool.parameters, func=tool.func)


class PluginRegistry:
    """
    Agent 可用的 Tool 與已連線的 MCP Adapter

    Tool 以名稱為 key；同名時後註冊者覆寫並記錄警告。
    """

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}
        self._mcp_adapters: Dict[str, BaseMCPAdapter] = {}

    def add_tool(self, tool: ToolLike) -> Tool:
        converted = as_hai_tool(tool)
        if converted.name in self._tools:
            logger.warning("Tool {!r} registered more than once, overriding", converted.name)
        self._tools[converted.name] = converted
        return converted

    def get_all_tools(self) -> List[Tool]:
        return list(self._tools.values())

    def get_tool(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def remove_tool(self, name: str, tool: Optional[Tool] = None) -> None:
        """移除工具；指定 tool 時只在目前註冊的就是該實例才移除（避免誤刪後來覆寫的同名工具）"""
        if tool is None or self._tools.get(name) is tool:
            self._tools.pop(name, None)

    def add_mcp(self, name: str, adapter: BaseMCPAdapter) -> None:
        self._mcp_adapters[name] = adapter

    def get_mcp(self, name: str) -> Optional[BaseMCPAdapter]:
        return self._mcp_adapters.get(name)

    def remove_mcp(self, name: str) -> None:
        self._mcp_adapters.pop(name, None)


@dataclass
class _Registrations:
    """單一插件透過 PluginContext 註冊的所有東西，停用 / 卸載時據此移除"""

    hooks: List[BaseHook] = field(default_factory=list)
    tools: List[Tool] = field(default_factory=list)
    commands: List[Tuple[CommandDefinition, CommandHandler]] = field(default_factory=list)
    mcps: Dict[str, BaseMCPAdapter] = field(default_factory=dict)
    adapter_types: List[str] = field(default_factory=list)


class _PluginContextImpl:
    """PluginContext 的具體實作，注入給插件的 on_load()"""

    def __init__(
        self,
        manager: "PluginManager",
        registrations: _Registrations,
        config: Dict[str, Any],
    ) -> None:
        self._manager = manager
        self._reg = registrations
        self.config = config
        self.gateway_config = manager._gateway_config()
        self.store: ConversationService = manager._store
        self.sessions: SessionService = manager._sessions
        self.voice: Optional[VoiceServiceProtocol] = manager._voice

    def register_hook(self, hook: BaseHook) -> None:
        self._reg.hooks.append(hook)
        self._manager._hook_registry.register(hook)

    def register_tool(self, tool: ToolLike) -> None:
        self._reg.tools.append(self._manager._plugin_registry.add_tool(tool))

    async def register_mcp(self, name: str, adapter: BaseMCPAdapter) -> None:
        await self._manager._require_mcp().add(name, adapter)
        self._reg.mcps[name] = adapter

    async def register_adapter(self, adapter: BaseGatewayAdapter) -> None:
        await self._manager._gateway.mount_adapter(adapter)

    def register_adapter_type(self, adapter_type: type[BaseGatewayAdapter]) -> None:
        service = self._manager._gateway_config_service
        if service is None:
            return
        service.register_adapter_type(adapter_type)
        self.gateway_config = service.get_config()
        if adapter_type.name not in self._reg.adapter_types:
            self._reg.adapter_types.append(adapter_type.name)

    def register_command(self, definition: CommandDefinition, handler: CommandHandler) -> None:
        self._manager._require_commands().register(definition, handler)
        self._reg.commands.append((definition, handler))


class PluginManager:
    """
    插件生命週期管理：load / enable / disable / unload

    disable 會暫時移除插件註冊的 hook / tool / 指令 / MCP，enable 時重新掛上；
    已掛載的 gateway adapter 與 adapter type 只在 unload 時處理。
    """

    def __init__(
        self,
        hook_registry: "HookRegistry",
        plugin_registry: PluginRegistry,
        store: ConversationService,
        sessions: SessionService,
        gateway: "GatewayCore",
        gateway_config_service: Optional["GatewayConfigService"] = None,
        voice: Optional[VoiceServiceProtocol] = None,
        mcp_manager: Optional["MCPManager"] = None,
    ) -> None:
        self._hook_registry = hook_registry
        self._plugin_registry = plugin_registry
        self._store = store
        self._sessions = sessions
        self._gateway = gateway
        self._gateway_config_service = gateway_config_service
        self._voice = voice
        self._mcp_manager = mcp_manager
        self._command_service: Optional["CommandService"] = None
        self._plugins: Dict[str, Tuple[BasePlugin, PluginState]] = {}
        self._registrations: Dict[str, _Registrations] = {}

    def set_command_service(self, service: "CommandService") -> None:
        self._command_service = service

    def _gateway_config(self) -> Dict[str, Any]:
        return {} if self._gateway_config_service is None else self._gateway_config_service.get_config()

    def _require_mcp(self) -> "MCPManager":
        if self._mcp_manager is None:
            raise RuntimeError("PluginManager: MCP manager not configured")
        return self._mcp_manager

    def _require_commands(self) -> "CommandService":
        if self._command_service is None:
            raise RuntimeError("PluginManager: command service not configured")
        return self._command_service

    async def load(self, plugin: BasePlugin, config: Optional[Dict[str, Any]] = None) -> None:
        name = plugin.name
        if name in self._plugins:
            raise ValueError(f"Plugin {name!r} is already loaded")
        reg = _Registrations()
        self._plugins[name] = (plugin, PluginState.loading)
        self._registrations[name] = reg
        try:
            await plugin.on_load(_PluginContextImpl(self, reg, config or {}))
            await plugin.on_enable()
            self._plugins[name] = (plugin, PluginState.enabled)
            logger.info("Plugin loaded: {} v{}", name, plugin.version)
        except Exception:
            self._plugins[name] = (plugin, PluginState.error)
            await self._detach(reg)
            self._remove_adapter_types(reg)
            logger.exception("Plugin load error: {}", name)
            raise

    async def unload(self, name: str) -> None:
        plugin, state = self._plugins[name]
        reg = self._registrations.pop(name)
        if state == PluginState.enabled:
            await self._detach(reg)
            await plugin.on_disable()
        self._remove_adapter_types(reg)
        await plugin.on_unload()
        del self._plugins[name]
        logger.info("Plugin unloaded: {}", name)

    async def enable(self, name: str) -> None:
        plugin, state = self._plugins[name]
        if state == PluginState.enabled:
            return
        await self._attach(self._registrations[name])
        await plugin.on_enable()
        self._plugins[name] = (plugin, PluginState.enabled)

    async def disable(self, name: str) -> None:
        plugin, state = self._plugins[name]
        if state != PluginState.enabled:
            return
        await self._detach(self._registrations[name])
        await plugin.on_disable()
        self._plugins[name] = (plugin, PluginState.disabled)

    def list(self) -> List[Dict[str, Any]]:
        return [
            {"name": n, "state": s.value, "version": p.version, "description": p.description}
            for n, (p, s) in self._plugins.items()
        ]

    def registered(self, name: str) -> Dict[str, List[str]]:
        reg = self._registrations[name]
        return {
            "hooks": [h.name for h in reg.hooks],
            "tools": [t.name for t in reg.tools],
            "commands": [d.name for d, _ in reg.commands],
            "mcps": list(reg.mcps),
            "adapter_types": list(reg.adapter_types),
        }

    async def _attach(self, reg: _Registrations) -> None:
        for hook in reg.hooks:
            self._hook_registry.register(hook)
        reg.tools = [self._plugin_registry.add_tool(t) for t in reg.tools]
        for definition, handler in reg.commands:
            self._require_commands().register(definition, handler)
        for mcp_name, adapter in reg.mcps.items():
            await self._require_mcp().add(mcp_name, adapter)

    async def _detach(self, reg: _Registrations) -> None:
        for hook in reg.hooks:
            self._hook_registry.unregister(hook)
        for tool in reg.tools:
            self._plugin_registry.remove_tool(tool.name, tool)
        if self._command_service is not None:
            for definition, handler in reg.commands:
                self._command_service.unregister(definition.name, handler)
        if self._mcp_manager is not None:
            for mcp_name in reg.mcps:
                await self._mcp_manager.remove(mcp_name)

    def _remove_adapter_types(self, reg: _Registrations) -> None:
        if self._gateway_config_service is None:
            return
        for adapter_type_name in reg.adapter_types:
            self._gateway_config_service.remove_adapter_type(adapter_type_name)


from .builtin import HookPlugin, ToolPlugin  # noqa: E402

__all__ = ["HookPlugin", "PluginManager", "PluginRegistry", "PluginState", "ToolPlugin", "as_hai_tool"]
