import json
import logging
import time
from typing import Any, Dict, Optional

from hai.providers.providers import ProviderSTT, ProviderText, ProviderTTS
from waifu.agent import AgentRunner, ContextBuilder
from waifu.config import ProviderConfig, VoiceConfig, WaifuConfig
from waifu.gateway import GatewayCore
from waifu.hook import HookPipeline, HookRegistry
from waifu.hook.builtin import EmotionHook, LoggingHook, MemoryHook, TTSHook
from waifu.plugin import PluginManager, PluginRegistry
from waifu.plugin.loader import PluginLoader
from waifu.service.character import CharacterService
from waifu.service.config import AppConfigService
from waifu.service.mcp import MCPService
from waifu.service.plugin import PluginService
from waifu.store import AppPaths, CharacterManager, Database, FileMemoryStore
from waifu.store.conversation import ConversationStore
from waifu.store.repositories import (
    AppConfigRepository,
    CharacterRepository,
    MCPRepository,
    PluginRepository,
    RelationshipRepository,
)
from waifu.voice import VoiceService
from waifu_types import BaseGatewayAdapter, BaseHook, BasePlugin, HookContext, IncomingRequest, OutgoingResponse

logger = logging.getLogger(__name__)


def _config_seed(config: "WaifuConfig") -> dict:
    """Flatten WaifuConfig into dotted key/value pairs for DB seeding."""
    entries: dict = {}
    for field, value in config.gateway.model_dump().items():
        entries[f"gateway.{field}"] = value
    for field, value in config.context.model_dump(exclude={"soul_content"}).items():
        entries[f"context.{field}"] = value
    for field, value in config.provider.model_dump().items():
        entries[f"provider.{field}"] = value
    return entries


def _build_provider(config: "ProviderConfig") -> ProviderText:
    """從 ProviderConfig 建立 ProviderText"""
    return ProviderText(
        name="waifu-provider",
        api_key=config.api_key,
        base_url=config.base_url,
        model=config.model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        stream=config.stream,
    )


def _build_voice_service(config: Optional[VoiceConfig]) -> Optional[VoiceService]:
    """從 VoiceConfig 建立 VoiceService，若未設定則回傳 None"""
    if config is None:
        return None
    stt = None
    tts = None
    if config.stt:
        stt = ProviderSTT(
            name="waifu-stt",
            api_key=config.stt.api_key,
            base_url=config.stt.base_url,
            model=config.stt.model,
            language=config.stt.language,
            temperature=config.stt.temperature,
        )
    if config.tts:
        tts = ProviderTTS(
            name="waifu-tts",
            api_key=config.tts.api_key,
            base_url=config.tts.base_url,
            model=config.tts.model,
            voice=config.tts.voice,
            response_format=config.tts.response_format,
            speed=config.tts.speed,
        )
    return VoiceService(stt=stt, tts=tts, lipsync_fps=config.lipsync_fps)


class Waifu:
    """
    組裝根（Composition Root）：將所有元件以 DI 方式組合

    不含業務邏輯，只負責建立依賴關係並串接資料流
    """

    def __init__(self, config: WaifuConfig, paths: Optional[AppPaths] = None) -> None:
        self._paths = paths or AppPaths.resolve()
        self._started_at: float = 0.0
        self._db = Database(self._paths.db_file)
        self._db.init()
        self._conversation_store = ConversationStore(conversations_dir=self._paths.conversations_dir)

        self._character_manager = CharacterManager(self._paths.characters_dir)
        if config.character:
            config.context.soul_content = self._character_manager.load_soul(config.character)

        self._provider = _build_provider(config.provider)
        self._voice_service: Optional[VoiceService] = _build_voice_service(config.voice)

        # Hook
        self._hook_registry = HookRegistry()
        self._hook_pipeline = HookPipeline(self._hook_registry)
        self._register_builtin_hooks(config)

        # Agent
        self._context_builder = ContextBuilder(config.context)
        self._agent_runner = AgentRunner(self._provider)

        # Gateway（注入 dispatch handler）— 須在 PluginManager 之前，提供 session_manager
        self._gateway = GatewayCore(
            session_ttl=config.gateway.session_ttl,
            lane_max_queue=config.gateway.lane_max_queue,
        )

        # Plugin
        self._plugin_registry = PluginRegistry()
        self._register_builtin_tools()
        self._plugin_manager = PluginManager(
            hook_registry=self._hook_registry,
            plugin_registry=self._plugin_registry,
            store=self._conversation_store,
            sessions=self._gateway.session_manager,
            gateway=self._gateway,
            voice=self._voice_service,
        )
        self._gateway.set_dispatch_handler(self._dispatch)

        # Plugin Loader
        self._plugin_loader = PluginLoader(self._paths.plugins_dir)

        # Repositories
        self._plugin_repo = PluginRepository()
        self._mcp_repo = MCPRepository()
        self._config_repo = AppConfigRepository()
        self._character_repo = CharacterRepository()
        self._relationship_repo = RelationshipRepository()

        # Seed initial config into DB (only if keys don't already exist)
        self._config_repo.seed_if_absent(_config_seed(config))

        # Services
        self._plugin_service = PluginService(self._plugin_repo, self._plugin_manager, self._plugin_loader)
        self._mcp_service = MCPService(self._mcp_repo, self._plugin_manager)
        self._config_service = AppConfigService(self._config_repo, self._context_builder, self._agent_runner)
        self._character_service = CharacterService(self._character_repo, self._relationship_repo)

    def _register_builtin_hooks(self, config: WaifuConfig) -> None:
        """根據 config 自動掛載內建 hooks"""
        memory_store = None
        if config.character:
            memory_store = FileMemoryStore(
                memory_dir=self._paths.memory_dir,
                character_name=config.character,
                max_recent=config.context.max_history_messages,
            )

        self._hook_registry.register(
            MemoryHook(
                store=memory_store,
                max_history=config.context.max_history_messages,
            )
        )
        self._hook_registry.register(EmotionHook())
        if self._voice_service is not None and self._voice_service.has_tts:
            self._hook_registry.register(TTSHook(self._voice_service))
        self._hook_registry.register(LoggingHook())

    def _register_builtin_tools(self) -> None:
        """將 waifu/tool/ 下的內建工具預先注冊到 PluginRegistry"""
        from waifu.tool import read_tool, shell_tool, webfetch_tool, write_tool

        for t in (read_tool, write_tool, shell_tool, webfetch_tool):
            self._plugin_registry.add_tool(t)

    def mount(self, adapter: BaseGatewayAdapter) -> "Waifu":
        """掛載 Gateway Adapter（WebSocket / Discord / Telegram / HTTP）"""
        self._gateway.mount(adapter)
        return self

    def use(self, hook: BaseHook) -> "Waifu":
        """注冊 Hook（pre/post 鏈）"""
        self._hook_registry.register(hook)
        return self

    async def plugin(self, p: BasePlugin, config: Optional[Dict[str, Any]] = None) -> "Waifu":
        """載入並啟用插件"""
        await self._plugin_manager.load(p, config)
        return self

    async def start(self) -> None:
        """啟動所有已掛載的 Adapter，並從 DB 恢復持久化設定"""
        self._started_at = time.time()
        await self._restore_from_db()
        await self._gateway.start()

    async def _restore_from_db(self) -> None:
        """從 DB 恢復所有持久化設定到 runtime"""

        for key, value in self._config_service.get_all().items():
            self._config_service.set(key, value)

        for row in self._mcp_repo.list_enabled():
            try:
                cmd = json.loads(row.command) if row.command else None
                await self._mcp_service.add(row.name, row.type, cmd, row.url, {})
            except Exception:
                logger.exception("Failed to restore MCP server: %s", row.name)

        for row in self._plugin_repo.list_enabled():
            try:
                config = json.loads(row.config_json)
                plugin = self._plugin_loader.resolve(row.plugin_name)
                await self._plugin_manager.load(plugin, config)
            except Exception:
                logger.exception("Failed to restore plugin: %s", row.name)

    @property
    def gateway(self) -> GatewayCore:
        return self._gateway

    @property
    def plugin_manager(self) -> PluginManager:
        return self._plugin_manager

    @property
    def voice_service(self) -> Optional[VoiceService]:
        return self._voice_service

    @property
    def plugin_service(self) -> PluginService:
        return self._plugin_service

    @property
    def mcp_service(self) -> MCPService:
        return self._mcp_service

    @property
    def config_service(self) -> AppConfigService:
        return self._config_service

    @property
    def character_service(self) -> CharacterService:
        return self._character_service

    @property
    def conversation_store(self) -> ConversationStore:
        return self._conversation_store

    @property
    def plugin_registry(self) -> PluginRegistry:
        return self._plugin_registry

    @property
    def started_at(self) -> float:
        return self._started_at

    async def _dispatch(self, request: IncomingRequest) -> OutgoingResponse:
        """
        完整請求生命週期：
          Session → HookPipeline.pre → ContextBuilder → AgentRunner
          → HookPipeline.post → OutgoingResponse
        """
        session = self._gateway.session_manager.get_or_create(request.conversation_id)

        # Ensure the conversation row exists in DB
        if self._conversation_store.get(request.conversation_id) is None:
            self._conversation_store.create_with_id(
                request.conversation_id,
                title=request.conversation_id,
            )

        # Persist user message
        self._conversation_store.add_llm_message(
            request.conversation_id,
            {"role": "user", "content": request.content},
        )

        ctx = HookContext(
            request=request,
            session=session,
            messages=list(session.history),
        )

        # Pre hooks（限流、記憶注入、內容審核 ...）
        ctx = await self._hook_pipeline.run_pre(ctx)
        if ctx.abort:
            return self._build_response(request, content=ctx.response or "", ctx=ctx)

        # 組裝 AgentInput → 執行 shuvi Agent
        agent_input = await self._context_builder.build(ctx, self._plugin_registry)
        result = await self._agent_runner.run(ctx, agent_input)

        # 從結果訊息中取最後一條 assistant 回應
        final_content = ""
        for msg in reversed(result.messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                final_content = msg["content"]
                break

        ctx.response = final_content
        ctx.trace = result.trace

        # 更新 session 歷史（只追加本輪新訊息）並持久化至 DB
        new_messages = result.messages[len(session.history) :]
        session.add_messages(new_messages)
        for msg in new_messages:
            if msg.get("role") != "user":
                self._conversation_store.add_llm_message(request.conversation_id, msg)

        # Post hooks（情緒解析、記憶儲存、日誌 ...）
        ctx = await self._hook_pipeline.run_post(ctx)

        return self._build_response(request, content=ctx.response or final_content, ctx=ctx)

    @staticmethod
    def _build_response(request: IncomingRequest, content: str, ctx: HookContext) -> OutgoingResponse:
        return OutgoingResponse(
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            source=request.source,
            content=content,
            trace=ctx.trace,
            events=ctx.events,
            reply_fn=request.reply_fn,
        )
