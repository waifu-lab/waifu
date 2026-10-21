import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from hai.providers import ProviderText, create_text_provider

from waifu.agent import AgentRunner, ContextBuilder, UtilityAI
from waifu.agent.output import OutputPipeline
from waifu.card import CardImporter, CardParser
from waifu.config import ProviderConfig, WaifuConfig
from waifu.config.sync import ConfigSync
from waifu.cron import CronExecutor, CronScheduler
from waifu.gateway import GatewayCore
from waifu.gateway.session import SessionManager
from waifu.heartbeat import HeartbeatManager
from waifu.hook import HookPipeline, HookRegistry
from waifu.hook.builtin import EmotionHook, LoggingHook, RateLimitHook, TTSHook
from waifu.hook.memory import MemoryHook
from waifu.logger import logger
from waifu.mcp.manager import MCPManager
from waifu.node import NodeManager
from waifu.plugin import PluginManager, PluginRegistry
from waifu.plugin.deps import PluginDependencyInstaller
from waifu.plugin.facade import ConversationServiceFacade
from waifu.plugin.loader import PluginLoader
from waifu.service.character import CharacterService
from waifu.service.command import CommandService
from waifu.service.config import AppConfigService
from waifu.service.gateway import GatewayConfigService
from waifu.service.mcp import MCPService
from waifu.service.plugin import PluginService
from waifu.service.registry import ServiceRegistry
from waifu.service.skill import SkillService
from waifu.service.status import StatusService
from waifu.service.title import AutoTitleService
from waifu.skill import SkillPromptHook, SkillRegistry, make_skill_tool, scan_skills
from waifu.store import AppPaths, CharacterManager, CronStore, Database
from waifu.store.conversation import ConversationStore
from waifu.store.repositories import (
    AppConfigRepository,
    CharacterRepository,
    PluginRepository,
    RelationshipRepository,
    TokenAnalyticsRepository,
)
from waifu.voice import VoiceService
from waifu_types import (
    AssistantMessage,
    BaseGatewayAdapter,
    BaseHook,
    BaseMessage,
    BasePlugin,
    ConversationService,
    GenericMessage,
    HookContext,
    IncomingRequest,
    MessageParts,
    OutgoingResponse,
    ReplyFn,
    SessionService,
    StreamObserver,
    SystemMessage,
    ToolMessage,
    UserMessage,
    VoiceServiceProtocol,
)


def _to_waifu_message(m: Any) -> BaseMessage:
    d = m if isinstance(m, dict) else m.model_dump(exclude_none=True)
    role = d.get("role", "")
    if role == "user":
        raw = d.get("content", "")
        parts = raw if isinstance(raw, list) else [{"type": "text", "text": raw}]
        return UserMessage(content=parts)
    if role == "assistant":
        return AssistantMessage(content=d.get("content"), tool_calls=d.get("tool_calls"))
    if role == "tool":
        return ToolMessage(tool_call_id=d.get("tool_call_id", ""), content=d.get("content", ""))
    if role == "system":
        return SystemMessage(content=d.get("content", ""))
    return GenericMessage(**d)


def _build_provider(config: "ProviderConfig") -> ProviderText:
    return create_text_provider(
        provider=config.provider,  # type: ignore
        model=config.model,
        api_key=config.api_key,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        stream=True,
    )


def _build_utility_provider(config: "ProviderConfig") -> ProviderText:
    return create_text_provider(
        provider=config.provider,  # type: ignore
        model=config.model,
        api_key=config.api_key,
        temperature=0.3,
        max_tokens=config.max_tokens,
        stream=False,
    )


class Waifu:
    """
    組裝根（Composition Root）：將所有元件以 DI 方式組合，並負責單一請求的處理流程（_dispatch）
    """

    def __init__(
        self,
        config: WaifuConfig,
        paths: Optional[AppPaths] = None,
        localmode: Optional[bool] = False,
        gateway_config_service: Optional[GatewayConfigService] = None,
        config_path: Optional[Path] = None,
    ) -> None:
        """config_path：與 DB 同步的 config.toml，預設為 paths.config_file"""
        self._config = config
        self._localmode: bool = bool(localmode)
        self._paths = paths or AppPaths.resolve()
        self._started_at: float = 0.0
        self._db = Database(self._paths.db_file)
        self._db.init()
        self._conversation_store = ConversationStore(
            conversations_dir=self._paths.conversations_dir,
            attachments_dir=self._paths.attachments_dir,
        )

        self._character_manager = CharacterManager(self._paths.characters_dir)
        soul_content: Optional[str] = None
        if config.character:
            soul_content = self._character_manager.load_soul(config.character)

        self._provider = _build_provider(config.provider)

        _util_cfg = config.utility_provider or config.provider
        self._utility_ai = UtilityAI(_build_utility_provider(_util_cfg))
        self._auto_title = AutoTitleService(self._conversation_store, self._utility_ai)
        self._voice_service: Optional[VoiceService] = VoiceService.from_config(config.voice) if config.voice else None

        # Hook
        self._hook_registry = HookRegistry()
        self._hook_pipeline = HookPipeline(self._hook_registry)
        self._output = OutputPipeline(self._hook_registry)
        self._memory_hook = self._register_builtin_hooks(config)

        # Agent
        self._context_builder = ContextBuilder(config.context, hook_registry=self._hook_registry, paths=self._paths)
        self._context_builder.set_soul_content(soul_content)
        self._agent_runner = AgentRunner(self._provider)

        # Gateway（注入 dispatch handler）— 須在 PluginManager 之前，提供 session_manager
        self._gateway = GatewayCore(
            session_ttl=config.gateway.session_ttl,
            lane_max_queue=config.gateway.lane_max_queue,
        )

        # Plugin
        self._plugin_registry = PluginRegistry()
        self._node_manager = NodeManager(self._plugin_registry)

        self._skill_registry = SkillRegistry()
        for manifest in scan_skills(self._paths.skills_dir):
            self._skill_registry.add(manifest)
        logger.info("Loaded {} skill(s) from {}", len(self._skill_registry), self._paths.skills_dir)
        self._plugin_registry.add_tool(make_skill_tool(self._skill_registry))
        self._hook_registry.register(SkillPromptHook(self._skill_registry))

        self._mcp_manager = MCPManager(self._plugin_registry)

        conversation_service = ConversationServiceFacade(self._conversation_store)
        self._plugin_manager = PluginManager(
            hook_registry=self._hook_registry,
            plugin_registry=self._plugin_registry,
            store=conversation_service,
            sessions=self._gateway.session_manager,
            gateway=self._gateway,
            gateway_config_service=gateway_config_service,
            voice=self._voice_service,
            mcp_manager=self._mcp_manager,
        )
        self._gateway.set_dispatch_handler(self._dispatch)

        # Plugin Loader
        self._plugin_loader = PluginLoader(self._paths.plugins_dir, PluginDependencyInstaller())

        # Repositories
        self._cron_store = CronStore()
        self._register_builtin_tools()
        self._plugin_repo = PluginRepository()
        self._config_repo = AppConfigRepository()
        self._character_repo = CharacterRepository()
        self._relationship_repo = RelationshipRepository()

        self._config_sync = ConfigSync(self._config_repo, config_path or self._paths.config_file)
        self._config_sync.adopt(config)

        self._card_parser = CardParser()
        self._card_importer = CardImporter(cards_dir=self._paths.cards_dir, parser=self._card_parser)

        # Services
        self._plugin_service = PluginService(self._plugin_repo, self._plugin_manager, self._plugin_loader)
        self._mcp_service = MCPService(self._mcp_manager, self._paths.mcp_config_file)
        self._skill_service = SkillService(self._skill_registry, self._paths.skills_dir)
        self._config_service = AppConfigService(
            self._config_repo, self._context_builder, self._agent_runner, self._config_sync
        )
        voice_enabled = self._voice_service is not None
        self._status_service = StatusService(
            get_started_at=lambda: self._started_at,
            session_manager=self._gateway.session_manager,
            conversation_store=self._conversation_store,
            plugin_manager=self._plugin_manager,
            mcp_service=self._mcp_service,
            config_service=self._config_service,
            gateway_config_service=gateway_config_service,
            voice_enabled=voice_enabled,
            stt_enabled=bool(self._voice_service and self._voice_service.has_stt),
            tts_enabled=bool(self._voice_service and self._voice_service.has_tts),
        )
        self._command_service = CommandService(
            status_service=self._status_service,
            session_manager=self._gateway.session_manager,
            plugin_registry=self._plugin_registry,
            mcp_service=self._mcp_service,
            skill_service=self._skill_service,
            config_service=self._config_service,
        )
        self._command_service.on_reset(self._memory_hook.clear)
        self._gateway.set_command_service(self._command_service)
        self._plugin_manager.set_command_service(self._command_service)
        self._character_service = CharacterService(
            self._character_repo,
            self._relationship_repo,
            manager=self._character_manager,
            card_importer=self._card_importer,
        )
        self._token_analytics = TokenAnalyticsRepository()

        self._cron_executor = CronExecutor(dispatch_fn=self._gateway.dispatch_and_wait)
        self._cron_scheduler = CronScheduler(store=self._cron_store, executor=self._cron_executor)
        self._heartbeat_manager = HeartbeatManager(
            dispatch_fn=self._gateway.dispatch_and_wait,
            events=config.heartbeat,
        )

        self._services = ServiceRegistry()
        self._services.register(HeartbeatManager, self._heartbeat_manager)
        self._services.register(NodeManager, self._node_manager)
        self._services.register(SessionManager, self._gateway.session_manager)
        self._services.register(SessionService, self._gateway.session_manager)
        self._services.register(ConversationService, conversation_service)
        if self._voice_service is not None:
            self._services.register(VoiceService, self._voice_service)
            self._services.register(VoiceServiceProtocol, self._voice_service)

    def _register_builtin_hooks(self, config: WaifuConfig) -> MemoryHook:
        """根據 config 掛載內建 hooks，回傳 MemoryHook（供 /new 清除記憶）"""
        memory_store = config.memory.build(
            character=config.character,
            max_history=config.context.max_history_messages,
            memory_dir=self._paths.memory_dir,
        )
        logger.info(
            "Memory backend '{}' → {}",
            config.memory.backend,
            type(memory_store).__name__ if memory_store is not None else "in-memory (no persistence)",
        )
        memory_hook = MemoryHook(store=memory_store, max_history=config.context.max_history_messages)
        self._hook_registry.register(memory_hook)

        hooks = config.hooks
        if hooks.rate_limit_rpm:
            self._hook_registry.register(RateLimitHook(max_rpm=hooks.rate_limit_rpm))

        emotion_hook: Optional[EmotionHook] = None
        if hooks.emotion:
            emotion_hook = EmotionHook()
            self._hook_registry.register(emotion_hook)

        if hooks.tts and self._voice_service is not None and self._voice_service.has_tts:
            tts_hook = TTSHook(self._voice_service, clean=self._output.apply, emotion_hook=emotion_hook)
            self._hook_registry.register(tts_hook)

        if hooks.logging:
            self._hook_registry.register(LoggingHook())
        return memory_hook

    def _register_builtin_tools(self) -> None:
        """將 waifu/tool/ 下的內建工具預先注冊到 PluginRegistry"""
        from waifu.tool import (
            file_edit_tool,
            file_patch_tool,
            file_search_tool,
            make_cron_tool,
            read_tool,
            shell_tool,
            webfetch_tool,
            websearch_tool,
            write_tool,
        )

        for t in (
            read_tool,
            write_tool,
            shell_tool,
            webfetch_tool,
            websearch_tool,
            file_search_tool,
            file_edit_tool,
            file_patch_tool,
        ):
            self._plugin_registry.add_tool(t)

        self._plugin_registry.add_tool(make_cron_tool(self._cron_store))

    def mount(self, adapter: BaseGatewayAdapter) -> "Waifu":
        """掛載 Gateway Adapter（WebSocket / Discord / Telegram / HTTP / 第三方）"""
        adapter.on_mount(self._services)
        self._gateway.mount(adapter)
        return self

    @property
    def services(self) -> ServiceRegistry:
        return self._services

    @property
    def heartbeat_manager(self) -> HeartbeatManager:
        return self._heartbeat_manager

    def use(self, hook: BaseHook) -> "Waifu":
        """注冊 Hook（pre/post 鏈）"""
        self._hook_registry.register(hook)
        return self

    async def plugin(self, p: BasePlugin, config: Optional[Dict[str, Any]] = None) -> "Waifu":
        """載入並啟用插件"""
        await self._plugin_manager.load(p, config)
        return self

    async def start(self) -> None:
        """啟動所有已掛載的 Adapter，並恢復非 config 的持久化狀態"""
        self._started_at = time.time()
        self._import_cards_on_startup()
        await self._restore_persistent_state()
        self._gateway.capabilities.update(self._hook_registry.capabilities())
        await self._cron_scheduler.start()
        if not self._localmode:
            await self._gateway.start()

    async def stop(self) -> None:
        """停止 Scheduler、Gateway 與 MCP 連線"""
        await self._cron_scheduler.stop()
        await self._gateway.stop()
        await self._auto_title.wait_idle()
        await self._mcp_manager.shutdown()

    def _import_cards_on_startup(self) -> None:
        results, errors = self._character_service.import_all_cards(overwrite=False)
        imported = [r for r in results if r.status != "skipped"]
        skipped = [r for r in results if r.status == "skipped"]
        if imported:
            logger.info("Imported {} character card(s) from {}", len(imported), self._paths.cards_dir)
        if skipped:
            logger.info("Skipped {} existing character card(s) from {}", len(skipped), self._paths.cards_dir)
        if self._config.character:
            self._context_builder.set_soul_content(self._character_manager.load_soul(self._config.character))
        for path, exc in errors:
            logger.warning("Failed to import card {}: {}", path, exc)

    async def _restore_persistent_state(self) -> None:
        """恢復非 config 的持久化狀態。config.toml 已在初始化時同步到 DB。"""
        await self._mcp_service.load_all()

        for row in self._plugin_repo.list_enabled():
            try:
                config = json.loads(cast(str, row.config_json))
                await asyncio.to_thread(self._plugin_loader.ensure_dependencies, cast(str, row.plugin_name))
                plugin = self._plugin_loader.resolve(cast(str, row.plugin_name))
                await self._plugin_manager.load(plugin, config)
            except Exception:
                logger.exception("Failed to restore plugin: {}", row.name)

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
    def status_service(self) -> StatusService:
        return self._status_service

    @property
    def character_service(self) -> CharacterService:
        return self._character_service

    @property
    def token_analytics(self) -> TokenAnalyticsRepository:
        return self._token_analytics

    @property
    def conversation_store(self) -> ConversationStore:
        return self._conversation_store

    @property
    def paths(self) -> AppPaths:
        return self._paths

    @property
    def plugin_registry(self) -> PluginRegistry:
        return self._plugin_registry

    @property
    def skill_registry(self) -> SkillRegistry:
        return self._skill_registry

    @property
    def mcp_manager(self) -> MCPManager:
        return self._mcp_manager

    @property
    def skill_service(self) -> SkillService:
        return self._skill_service

    @property
    def card_importer(self) -> CardImporter:
        return self._card_importer

    @property
    def localmode(self) -> bool:
        return self._localmode

    async def dispatch(
        self,
        request: "IncomingRequest | MessageParts",
        *,
        conversation_id: Optional[str] = None,
        reply_fn: Optional[ReplyFn] = None,
    ) -> OutgoingResponse:
        """送出請求並等待回應；與 adapter 進來的訊息一樣經過該對話的 Lane"""
        if isinstance(request, MessageParts):
            request = request.to_request(
                conversation_id=conversation_id,
                reply_fn=reply_fn,
            )
        return await self._gateway.dispatch_and_wait(request)

    @property
    def started_at(self) -> float:
        return self._started_at

    async def _dispatch(self, request: IncomingRequest) -> OutgoingResponse:
        """
        單一請求的完整生命週期（由 Lane 呼叫，同一對話保證串行）：
          Session → HookPipeline.pre → ContextBuilder → AgentRunner
          → OutputPipeline → HookPipeline.mid → 持久化 → StreamObserver.finish → HookPipeline.post → OutgoingResponse
        AgentRunner 串流期間，原始 chunk 同時交給 hook 的 StreamObserver（例如 TTS 邊生成邊合成）
        """
        command_response = await self._command_service.try_execute(request)
        if command_response is not None:
            return command_response

        session = self._gateway.session_manager.get_or_create(request.conversation_id)
        conversation = self._conversation_store.get(request.conversation_id)
        if conversation is not None and not session.history:
            self._restore_session_history(request.conversation_id, session)

        # Ensure the conversation row exists in DB
        is_new_conversation = conversation is None
        if is_new_conversation:
            # 標題暫時為 conversation_id，由 AutoTitleService 於回覆後命名
            self._conversation_store.create_with_id(
                request.conversation_id,
                title=request.conversation_id,
                auto_title=True,
            )
            if request.metadata:
                session.metadata.update(request.metadata)

        self._conversation_store.add_llm_message(
            request.conversation_id,
            {"role": "user", "content": request.content},
            attachments=request.attachments or None,
        )

        ctx = HookContext(
            request=request,
            session=session,
            messages=list(session.history),
        )

        ctx = await self._hook_pipeline.run_pre(ctx)
        if ctx.abort:
            return self._build_response(request, content=ctx.response or "", ctx=ctx)

        system_prompt = self._context_builder.build_system_prompt(ctx)
        context_manager = self._context_builder.build_context_manager(ctx)
        tools = self._plugin_registry.get_all_tools()
        # Capture after hooks (MemoryHook.pre may have replaced ctx.messages with file-loaded history)
        history_len = len(ctx.messages)

        observer = self._hook_pipeline.stream_observer(ctx)
        try:
            return await self._run_and_respond(ctx, system_prompt, tools, context_manager, history_len, observer)
        finally:
            await observer.aclose()

    async def _run_and_respond(
        self,
        ctx: HookContext,
        system_prompt: str,
        tools: Any,
        context_manager: Any,
        history_len: int,
        observer: StreamObserver,
    ) -> OutgoingResponse:
        request = ctx.request
        session = ctx.session

        agent_result = await self._run_agent(ctx, system_prompt, tools, context_manager, observer)
        if isinstance(agent_result, OutgoingResponse):
            return agent_result

        final_content = ""
        for msg in reversed(agent_result.messages):
            if msg.role == "assistant" and isinstance(msg.content, str) and msg.content:
                final_content = msg.content
                break

        ctx.response = final_content
        ctx.trace = agent_result.trace

        # context_manager.history = [full_history..., user_msg, new_agent_msgs...]
        # Use context_manager.history (not agent_result.messages) so that context
        # truncation cannot cause user_msg to be dropped: agent_result.messages is
        # based on the *truncated* initial_messages, so slicing by history_len
        # would skip user_msg when len(ctx.messages) >= max_history_messages.
        # _persist_new_messages already skips role=="user" so no double-save.
        ctx.new_messages = self._clean_for_history(
            [_to_waifu_message(m) for m in context_manager.history[history_len:]]
        )
        ctx = await self._hook_pipeline.run_mid(ctx)

        session.add_messages(ctx.new_messages)
        self._persist_new_messages(request.conversation_id, ctx.new_messages, agent_result.trace.token_usage)

        await observer.finish()
        ctx = await self._hook_pipeline.run_post(ctx)

        display_content = self._output.apply(ctx.response or final_content).strip()
        self._auto_title.schedule(request, display_content)

        return self._build_response(request, content=display_content, ctx=ctx)

    def _clean_for_history(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """存入歷史前，對 assistant 文字套用 OutputTransformer（例如移除情緒標籤）"""
        for msg in messages:
            if isinstance(msg, AssistantMessage) and msg.content:
                msg.content = self._output.apply_history(msg.content).strip()
        return messages

    async def _run_agent(
        self, ctx: HookContext, system_prompt: str, tools: Any, context_manager: Any, observer: StreamObserver
    ) -> Any:
        request = ctx.request
        try:
            return await self._agent_runner.run(
                ctx, system_prompt, tools, context_manager, self._output.stream(), observer
            )
        except asyncio.CancelledError:
            logger.warning(
                "Request {} cancelled (interrupted or client disconnected), writing interrupt placeholder",
                request.request_id,
            )
            placeholder = {"role": "assistant", "content": "〔已中斷〕"}
            self._conversation_store.add_llm_message(request.conversation_id, placeholder)

            ctx.session.add_messages(
                [_to_waifu_message({"role": "user", "content": request.content}), _to_waifu_message(placeholder)]
            )
            raise
        except Exception:
            logger.exception("AgentRunner failed for request {}, writing fallback message", request.request_id)
            fallback = "系統發生錯誤，請稍後再試"
            self._conversation_store.add_llm_message(
                request.conversation_id,
                {"role": "assistant", "content": fallback},
            )
            ctx.response = fallback
            return self._build_response(request, content=fallback, ctx=ctx)

    def _persist_new_messages(self, conversation_id: str, new_messages: List[BaseMessage], usage: Any) -> None:
        assistant_indices = [i for i, m in enumerate(new_messages) if m.role == "assistant"]
        last_assistant_idx = assistant_indices[-1] if assistant_indices else -1
        for i, msg in enumerate(new_messages):
            if msg.role == "user":
                continue
            is_last_assistant = i == last_assistant_idx
            self._conversation_store.add_llm_message(
                conversation_id,
                msg.model_dump(exclude_none=True),
                input_tokens=usage.input if is_last_assistant else None,
                output_tokens=usage.output if is_last_assistant else None,
            )

    def _restore_session_history(self, conversation_id: str, session: Any) -> None:
        history = self._conversation_store.get_llm_messages(conversation_id, limit=0)
        if not history:
            return
        session.add_messages([_to_waifu_message(msg) for msg in history])

    @staticmethod
    def _build_response(request: IncomingRequest, content: str, ctx: HookContext) -> OutgoingResponse:
        return OutgoingResponse(
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            source=request.source,
            content=content,
            trace=ctx.trace,
            events=ctx.events,
        )
