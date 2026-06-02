import inspect
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from waifu.gateway.session import SessionManager
from waifu.plugin import PluginRegistry
from waifu.service.config import AppConfigService
from waifu.service.mcp import MCPService
from waifu.service.skill import SkillService
from waifu.service.status import StatusService
from waifu_types import IncomingRequest, OutgoingResponse

_COMMAND_RE = re.compile(r"^/([A-Za-z][\w-]*)(?:@[A-Za-z0-9_]+)?(?:\s+(.*))?$")


@dataclass(frozen=True)
class CommandArgument:
    name: str
    description: str
    required: bool = False


@dataclass(frozen=True)
class CommandDefinition:
    name: str
    description: str
    arguments: tuple[CommandArgument, ...] = ()


@dataclass(frozen=True)
class ParsedCommand:
    name: str
    args: str = ""


class CommandService:
    def __init__(
        self,
        *,
        status_service: StatusService,
        session_manager: SessionManager,
        plugin_registry: PluginRegistry,
        mcp_service: MCPService,
        skill_service: SkillService,
        config_service: AppConfigService,
        memory_clear: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> None:
        self._status_service = status_service
        self._session_manager = session_manager
        self._plugin_registry = plugin_registry
        self._mcp_service = mcp_service
        self._skill_service = skill_service
        self._config_service = config_service
        self._memory_clear = memory_clear
        self._definitions = (
            CommandDefinition("health", "Check Waifu health"),
            CommandDefinition("status", "Show Waifu runtime status"),
            CommandDefinition("tools", "List available tools"),
            CommandDefinition("mcps", "List configured MCP servers"),
            CommandDefinition("skills", "List installed skills"),
            CommandDefinition(
                "model",
                "Show the current model",
                arguments=(CommandArgument("model", "Optional model name", required=False),),
            ),
            CommandDefinition("models", "Show model discovery status"),
            CommandDefinition("new", "Start a new context for this chat"),
        )
        self._handlers = {
            "health": self._health,
            "status": self._status,
            "tools": self._tools,
            "mcps": self._mcps,
            "skills": self._skills,
            "model": self._model,
            "models": self._models,
            "new": self._new,
        }

    @property
    def definitions(self) -> tuple[CommandDefinition, ...]:
        return self._definitions

    def parse(self, content: str) -> Optional[ParsedCommand]:
        match = _COMMAND_RE.match(content.strip())
        if not match:
            return None
        name = match.group(1).lower()
        args = (match.group(2) or "").strip()
        return ParsedCommand(name=name, args=args)

    async def try_execute(self, request: IncomingRequest) -> Optional[OutgoingResponse]:
        parsed = self.parse(request.content)
        if parsed is None:
            return None

        handler = self._handlers.get(parsed.name)
        if handler is None:
            if request.metadata.get("platform_command"):
                return self._response(request, self._unknown_command(parsed.name))
            return None

        content = await handler(request, parsed.args)
        return self._response(request, content)

    async def _health(self, _request: IncomingRequest, _args: str) -> str:
        return "OK"

    async def _status(self, _request: IncomingRequest, _args: str) -> str:
        status = self._status_service.get_status()
        provider = status.get("provider", {})
        voice = status.get("voice", {})
        plugins = status.get("plugins_loaded", [])
        mcps = status.get("mcp_servers", [])
        lines = [
            "Status",
            f"Uptime: {_format_duration(int(status.get('uptime_seconds') or 0))}",
            f"Active sessions: {status.get('active_sessions', 0)}",
            f"Conversations: {status.get('active_conversations', 0)}",
            f"Model: {provider.get('model') or '-'}",
        ]
        if provider.get("base_url"):
            lines.append(f"Base URL: {provider['base_url']}")
        lines.append(f"Plugins: {', '.join(plugins) if plugins else '-'}")
        lines.append(f"MCP servers: {len(mcps)} configured")
        lines.append(
            "Voice: "
            f"{'enabled' if voice.get('enabled') else 'disabled'}"
            f" (STT: {_yes_no(voice.get('stt_enabled'))}, TTS: {_yes_no(voice.get('tts_enabled'))})"
        )
        return "\n".join(lines)

    async def _tools(self, _request: IncomingRequest, _args: str) -> str:
        tools = self._plugin_registry.get_all_tools()
        if not tools:
            return "No tools registered."
        lines = [f"Tools: {len(tools)} available"]
        for tool in tools[:20]:
            name = getattr(tool, "name", "<unnamed>")
            description = _single_line(getattr(tool, "description", ""))
            lines.append(f"- {name}: {description}" if description else f"- {name}")
        if len(tools) > 20:
            lines.append(f"...and {len(tools) - 20} more")
        return "\n".join(lines)

    async def _mcps(self, _request: IncomingRequest, _args: str) -> str:
        rows = self._mcp_service.list_all()
        if not rows:
            return "No MCP servers configured."
        lines = [f"MCP servers: {len(rows)} configured"]
        for row in rows[:20]:
            enabled = "enabled" if row.get("enabled", True) else "disabled"
            target = _format_target(row.get("target"))
            suffix = f" → {target}" if target else ""
            lines.append(f"- {row.get('name')}: {row.get('type')} {enabled}{suffix}")
        if len(rows) > 20:
            lines.append(f"...and {len(rows) - 20} more")
        return "\n".join(lines)

    async def _skills(self, _request: IncomingRequest, _args: str) -> str:
        rows = self._skill_service.list()
        if not rows:
            return "No skills installed."
        lines = [f"Skills: {len(rows)} installed"]
        for row in rows[:20]:
            description = _single_line(str(row.get("description") or ""))
            lines.append(f"- {row.get('name')}: {description}" if description else f"- {row.get('name')}")
        if len(rows) > 20:
            lines.append(f"...and {len(rows) - 20} more")
        return "\n".join(lines)

    async def _model(self, _request: IncomingRequest, args: str) -> str:
        model = self._config_service.get("provider.model")
        base_url = self._config_service.get("provider.base_url")
        lines = [f"Current model: {model or '-'}"]
        if base_url:
            lines.append(f"Base URL: {base_url}")
        if args:
            lines.append("Model switching from platform commands is not enabled yet.")
        return "\n".join(lines)

    async def _models(self, _request: IncomingRequest, _args: str) -> str:
        model = self._config_service.get("provider.model")
        return (
            f"Current model: {model or '-'}\n"
            "Provider model discovery is not available yet. "
            "Use the configured provider model name in config or API settings."
        )

    async def _new(self, request: IncomingRequest, _args: str) -> str:
        self._session_manager.delete(request.conversation_id)
        if self._memory_clear is not None:
            result = self._memory_clear(request.conversation_id)
            if inspect.isawaitable(result):
                await result
        return "Started a new context for this chat."

    def _unknown_command(self, name: str) -> str:
        available = ", ".join(f"/{d.name}" for d in self._definitions)
        return f"Unknown command: /{name}\nAvailable commands: {available}"

    @staticmethod
    def _response(request: IncomingRequest, content: str) -> OutgoingResponse:
        return OutgoingResponse(
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            source=request.source,
            content=content,
            reply_fn=request.reply_fn,
        )


def _format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec}s"
    hours, minute = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minute}m"
    days, hour = divmod(hours, 24)
    return f"{days}d {hour}h"


def _format_target(target: object) -> str:
    if isinstance(target, list):
        return " ".join(str(p) for p in target[:3])[:80]
    if target is None:
        return ""
    return str(target)[:80]


def _single_line(text: str, limit: int = 100) -> str:
    value = " ".join(text.split())
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _yes_no(value: object) -> str:
    return "yes" if value else "no"
