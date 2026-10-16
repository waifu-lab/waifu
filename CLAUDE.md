# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies (uv workspace)
uv sync

# Run the server (development with hot reload)
waifu start --config config.toml --reload

# Run the server with a custom FastAPI app
waifu start --app myapp:app --host 0.0.0.0 --port 8765

# Lint
uvx ruff check waifu/ waifu_types/
uvx ruff check --fix waifu/ waifu_types/

# Format
uvx ruff format waifu/ waifu_types/
```

Config file formats supported: `.toml`, `.yaml`/`.yml`, `.json`.

## Architecture

This is a **uv workspace monorepo** with three packages:

- `waifu_types/` — Shared ABCs/Protocols/Pydantic models (only depends on pydantic). The source of truth for all interfaces.
- `waifu_sdk/` — Re-export of `waifu_types` (plus `hai.tool.Tool`) for third-party plugin authors. Never put definitions here.
- `waifu/` — Server implementation (depends on `waifu_types`, `fastapi`, `hai`, `shuvi`).

### Request Lifecycle

```
Adapter (WS/Discord/Telegram/HTTP) / cron / heartbeat / Waifu.dispatch()
  → IncomingRequest
  → GatewayCore.dispatch() / dispatch_and_wait()
  → Lane[conversation_id].enqueue()   ← per-conversation serial queue (everything goes through here)
  → Waifu._dispatch()
      → CommandService.try_execute()  ← /commands short-circuit
      → HookPipeline.run_pre()
      → ContextBuilder                ← system prompt (hooks add via contribute_prompt) + messages
      → AgentRunner.run()             ← shuvi.Agent; stream chunks pass through OutputPipeline.stream()
      → OutputPipeline.apply_history  ← new assistant messages cleaned before mid / persistence
      → HookPipeline.run_mid() → persist → HookPipeline.run_post()
      → OutputPipeline.apply          ← display content
  → OutgoingResponse
  → request.reply(response)           ← GatewayCore calls reply_fn(response)
```

`reply_fn` is the only delivery channel (`reply_fn(response)` / `reply_fn(chunk=str)` / `reply_fn(event=Event)`). Internal code calls `request.reply_chunk()` / `reply_event()` / `reply()` instead of invoking it directly.

### Key Modules

**`waifu/waifu.py` — `Waifu` class (Composition Root)**
The top-level class that wires everything together using a fluent builder API:
```python
waifu = (
    Waifu(config)
    .mount(WebSocketAdapter())
    .mount(DiscordAdapter(token=TOKEN))
    .use(RateLimitHook(max_rpm=60))
)
await waifu.mcp_service.add("fs", "stdio", command=[...])
await waifu.start()
```

**`waifu/gateway/`** — Ingress layer (`GatewayCore` implements `waifu_types.GatewayProtocol`)
- `GatewayCore`: mounts adapters, manages sessions, dispatches to lane queues
- `SessionManager`: TTL-based session store keyed by `conversation_id`
- `LaneManager`: one `asyncio.Queue` per `conversation_id` ensuring serial processing; idle lanes are released
- `adapters/`: `WebSocketAdapter` (SESSION mode, chunk streaming + Live2D events), `DiscordAdapter`, `TelegramAdapter`, `HTTPAdapter` (SSE), `WaifuNodeAdapter`
- Adapters get runtime services via `on_mount(services)` (`services.get(HeartbeatManager)` etc.) and expose endpoints via `routers()`; never special-case an adapter type in `Waifu`

**`waifu/hook/`** — Pre/mid/post middleware chain
- `BaseHook` (from `waifu_types`): `pre` / `mid` / `post`, `contribute_prompt`, `output_transformers`, `capabilities`; `priority` (lower = earlier)
- `HookContext`: `request`, `session`, `messages`, `response` (raw LLM output), `events`, `abort`, `new_messages`, `handled` (cross-hook "already done" flags)
- Built-in hooks in `waifu/hook/builtin.py`: `RateLimitHook`, `EmotionHook`, `LoggingHook`, `TTSHook`; `MemoryHook` in `memory.py`. Toggled by `WaifuConfig.hooks`
- Memory backends: subclass `MemoryBackendConfig` (`backend` literal + `build()`) and add it to the `MemoryConfig` union in `waifu/config/__init__.py` — same pattern as TTS backends

**Inline output tags** — LLM output markup like `[emotion:happy]` is owned by the hook that defines it: return an `InlineTagTransformer` from `output_transformers()`; `waifu/agent/output.py` `OutputPipeline` applies it to stream chunks, display text, history and TTS text. Do not add tag regexes anywhere else.

**`waifu/plugin/`** — Plugin system
- `PluginManager.load(plugin, config)` calls `plugin.on_load(ctx)`; plugins register hooks / tools / commands / MCP / adapters through `PluginContext`
- `disable` detaches everything the plugin registered, `enable` re-attaches, `unload` removes
- `PluginRegistry`: tools (by name, `ToolLike` converted to `hai.tool.Tool`) and connected MCP adapters
- `ConversationServiceFacade` (`facade.py`) gives plugins typed `ConversationInfo` / `StoredMessage` instead of peewee rows
- Built-in plugin wrappers in `waifu/plugin/builtin.py`: `ToolPlugin`, `HookPlugin`

**`waifu/mcp/`** — MCP bridge (system-level, not a plugin)
- `MCPManager`: owns adapter lifecycle, registers tools into `PluginRegistry`
- `StdioMCPAdapter`: spawns a subprocess (JSON-RPC over stdin/stdout)
- `SSEMCPAdapter`: connects to HTTP SSE MCP server

**`waifu/router/`** — FastAPI routers
- `GET /health`, `GET|POST|DELETE /plugins/*`, `/status`, … mounted by `include_routers(app, **services)` (factory functions, no `Depends`)
- Adapter endpoints (`WS /ws`, `POST /chat` SSE, `WS /node`) come from each adapter's `routers()` in `_cli_app.py`

**`waifu/voice/`** — Optional voice pipeline
- `VoiceService`: STT (Whisper-compatible) → text → TTS → audio + lipsync events
- Enabled via `VoiceConfig` in `WaifuConfig`; WebSocket adapter handles `type:"voice"` messages

### Conversation Modes

| Mode      | `conversation_id` key          | History scope         | Multi-user                |
| --------- | ------------------------------ | --------------------- | ------------------------- |
| `SESSION` | `ws:{session_token}`           | Per WebSocket session | No                        |
| `DIRECT`  | `{source}:dm:{user_id}`        | Per user, persistent  | No                        |
| `GROUP`   | `{source}:{room/channel}:{id}` | Per room, persistent  | Yes (author prefix added) |

GROUP mode: history messages get `[DisplayName]:` prefix; adapter only dispatches on `@mention` or `/shuvi`.

### Configuration (`WaifuConfig`)

```python
class WaifuConfig(BaseModel):
    gateway: GatewayConfig    # host, port, session_ttl, lane_max_queue
    context: ContextConfig    # builtin_prompt, system_prompt_template, max_history_messages, history_strategy
    memory: MemoryConfig      # backend ("auto"/"none"/"file"/"history_tree"/registered)
    hooks: HooksConfig        # emotion, tts, logging, rate_limit_rpm
    heartbeat: Optional[List[HeartbeatEventConfig]]  # None = built-in events
    provider: ProviderConfig  # api_key, base_url, model, temperature, stream
    voice: Optional[VoiceConfig]  # stt, tts (discriminated by tts.backend), lipsync_fps, translation
    node: Optional[WaifuNodeConfig]
```

**Source of truth is the DB** (`app_config`, flattened dotted keys); `config.toml` is the user-facing editing surface. `waifu/config/sync.py` `ConfigSync`: on load / every `AppConfigService.set`, keys the user changed in the toml (vs. the last-sync snapshot) are merged into the DB, the result is validated by `WaifuConfig`, then written back to both DB and toml (tomlkit keeps comments; original line endings kept). Never write config to the DB without going through `ConfigSync`.

TTS backends: subclass `TTSBackendConfig` with a `backend` literal and `build()`, add it to the `TTSConfig` union in `waifu/config/__init__.py`.

The system prompt is ordered most-stable first (`SystemPromptLayers`); anything that changes per request (time, user) goes in the `runtime` layer so the provider prompt cache can hit.

### Third-party Extension

Plugin/adapter authors install `waifu-sdk` (re-exports `waifu_types`). All ABCs are in `waifu_types/waifu_types/`:
- `BasePlugin` + `PluginContext` — `plugin.py`
- `BaseGatewayAdapter` — `adapter.py`; `GatewayProtocol` — `gateway.py`
- `BaseHook` + `HookContext` — `hook.py`
- `OutputTransformer` / `InlineTagTransformer` — `output.py`
- `BaseMCPAdapter` — `mcp.py`
- `ToolLike` / `FunctionTool` / `@tool` — `tool.py`
- `CommandDefinition` / `CommandHandler` — `command.py`
- Service protocols (`ConversationService`, `SessionService`, `VoiceServiceProtocol`, `ServiceProvider`) — `services.py`
- `Feature` / `SessionMeta` / `RequestMeta` well-known keys — `keys.py`
- `IncomingRequest`, `OutgoingResponse`, `Event`, `ReplyFn`, `Attachment`, messages — `types.py`

Line endings: the project is developed on Windows; `.editorconfig` and `.gitattributes` use CRLF (shell scripts stay LF).

### External Dependencies

- **`hai`** — LLM providers (OpenAI/Anthropic/Google/Ollama), tools, loaders, vector/graph stores
- **`shuvi`** — Agent inner/outer loop with tool-calling; `shuvi.Agent` takes `AgentConfig` + messages
- **`fastapi`** + **`uvicorn`** — HTTP/WebSocket server
- **`discord.py`** — Discord adapter (optional)
- **`python-telegram-bot`** — Telegram adapter (optional)
