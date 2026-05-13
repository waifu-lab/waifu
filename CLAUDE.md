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
- `waifu_sdk/` — Thin re-export of `waifu_types` for third-party plugin authors.
- `waifu/` — Server implementation (depends on `waifu_types`, `fastapi`, `hai`, `shuvi`).

### Request Lifecycle

```
Adapter (WS/Discord/Telegram/HTTP)
  → IncomingRequest
  → GatewayCore.dispatch()
  → Lane[conversation_id].enqueue()   ← per-conversation serial queue
  → HookPipeline.run_pre()
  → ContextBuilder.build()            ← assembles system_prompt + messages + tools
  → AgentRunner.run()                 ← wraps shuvi.Agent (tool-calling loop)
  → HookPipeline.run_post()
  → OutgoingResponse
  → Adapter.send()
```

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

**`waifu/gateway/`** — Ingress layer
- `GatewayCore`: mounts adapters, manages sessions, dispatches to lane queues
- `SessionManager`: TTL-based session store keyed by `conversation_id`
- `LaneManager`: one `asyncio.Queue` per `conversation_id` ensuring serial processing
- `adapters/`: `WebSocketAdapter` (SESSION mode, chunk streaming + Live2D events), `DiscordAdapter`, `TelegramAdapter`, `HTTPAdapter` (SSE)

**`waifu/hook/`** — Pre/post middleware chain
- `BaseHook` (from `waifu_types`): `async pre(ctx)` and `async post(ctx)` with `priority` (lower = earlier)
- `HookContext`: carries `request`, `session`, `messages`, `response`, `events`, `abort`
- Built-in hooks in `waifu/hook/builtin.py`: `RateLimitHook`, `MemoryHook`, `EmotionHook`, `LoggingHook`, `TTSHook`

**`waifu/plugin/`** — Plugin system
- `PluginManager.load(plugin, config)` calls `plugin.on_load(ctx)` where plugins register hooks/tools/MCP adapters
- `PluginRegistry`: holds all registered tools/MCP adapters for the `ContextBuilder`
- Built-in plugin wrappers in `waifu/plugin/builtin.py`: `ToolPlugin`, `HookPlugin`

**`waifu/mcp/`** — MCP bridge (system-level, not a plugin)
- `MCPManager`: owns adapter lifecycle, registers tools into `PluginRegistry`
- `StdioMCPAdapter`: spawns a subprocess (JSON-RPC over stdin/stdout)
- `SSEMCPAdapter`: connects to HTTP SSE MCP server

**`waifu/router/`** — FastAPI routers
- `GET /health`, `WS /ws`, `POST /chat` (SSE), `GET|POST|DELETE /plugins/*`
- `include_routers(app)` mounts all routers; uses `Depends(get_waifu)` for DI

**`waifu/voice/`** — Optional voice pipeline
- `VoiceService`: STT (Whisper-compatible) → text → TTS → audio + lipsync events
- Enabled via `VoiceConfig` in `WaifuConfig`; WebSocket adapter handles `type:"voice"` messages

### Conversation Modes

| Mode | `conversation_id` key | History scope | Multi-user |
|---|---|---|---|
| `SESSION` | `ws:{session_token}` | Per WebSocket session | No |
| `DIRECT` | `{source}:dm:{user_id}` | Per user, persistent | No |
| `GROUP` | `{source}:{room/channel}:{id}` | Per room, persistent | Yes (author prefix added) |

GROUP mode: history messages get `[DisplayName]:` prefix; adapter only dispatches on `@mention` or `/shuvi`.

### Configuration (`WaifuConfig`)

```python
class WaifuConfig(BaseModel):
    gateway: GatewayConfig    # host, port, session_ttl, lane_max_queue
    context: ContextConfig    # system_prompt_template, max_history_messages, history_strategy
    provider: ProviderConfig  # api_key, base_url, model, temperature, stream
    voice: Optional[VoiceConfig]  # stt, tts, lipsync_fps
```

### Third-party Extension

Plugin/adapter authors install `waifu-sdk` (re-exports `waifu_types`). All ABCs are in `waifu_types/waifu_types/`:
- `BasePlugin` + `PluginContext` — `plugin.py`
- `BaseGatewayAdapter` — `adapter.py`
- `BaseHook` + `HookContext` — `hook.py`
- `BaseMCPAdapter` — `mcp.py`
- `IncomingRequest`, `OutgoingResponse`, `Attachment` — `types.py`

### External Dependencies

- **`hai`** — LLM providers (OpenAI/Anthropic/Google/Ollama), tools, loaders, vector/graph stores
- **`shuvi`** — Agent inner/outer loop with tool-calling; `shuvi.Agent` takes `AgentConfig` + messages
- **`fastapi`** + **`uvicorn`** — HTTP/WebSocket server
- **`discord.py`** — Discord adapter (optional)
- **`python-telegram-bot`** — Telegram adapter (optional)
