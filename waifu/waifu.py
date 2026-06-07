import asyncio
import json
import re
import time
from typing import Any, Dict, Optional, cast

from hai.providers import ProviderSTT, ProviderText, ProviderTTS, create_text_provider
from waifu.agent import AgentRunner, ContextBuilder, UtilityAI
from waifu.card import CardImporter, CardParser
from waifu.config import MemoryConfig, ProviderConfig, VoiceConfig, WaifuConfig
from waifu.cron import CronExecutor, CronScheduler
from waifu.gateway import GatewayCore
from waifu.heartbeat import HeartbeatManager
from waifu.hook import HookPipeline, HookRegistry
from waifu.hook.builtin import EmotionHook, LoggingHook, TTSHook
from waifu.hook.memory import MemoryHook
from waifu.logger import logger
from waifu.mcp.manager import MCPManager
from waifu.node import NodeManager
from waifu.plugin import PluginManager, PluginRegistry
from waifu.plugin.loader import PluginLoader
from waifu.service.character import CharacterService
from waifu.service.command import CommandService
from waifu.service.config import AppConfigService
from waifu.service.gateway import GatewayConfigService
from waifu.service.mcp import MCPService
from waifu.service.plugin import PluginService
from waifu.service.skill import SkillService
from waifu.service.status import StatusService
from waifu.skill import SkillPromptHook, SkillRegistry, make_skill_tool, scan_skills
from waifu.store import AppPaths, CharacterManager, CronStore, Database, FileMemoryStore, HistoryTreeStore
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
    GenericMessage,
    HookContext,
    IncomingRequest,
    MessageParts,
    OutgoingResponse,
    SystemMessage,
    ToolMessage,
    UserMessage,
)

# FIXME: 超醜
_EMOTION_TAG_RE = re.compile(r"\[emotion:\w+\]", re.IGNORECASE)


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


def _config_seed(config: "WaifuConfig") -> dict:
    """Flatten WaifuConfig into dotted key/value pairs for DB sync."""
    entries: dict = {}

    def add_section(prefix: str, data: dict) -> None:
        for field, value in data.items():
            key = f"{prefix}.{field}"
            if isinstance(value, dict):
                add_section(key, value)
            else:
                entries[key] = value

    add_section("gateway", config.gateway.model_dump())
    add_section(
        "context",
        config.context.model_dump(
            exclude_none=True,
        ),
    )
    add_section("memory", config.memory.model_dump(exclude_none=True))
    add_section("provider", config.provider.model_dump(exclude_none=True))
    if config.utility_provider is not None:
        add_section("utility_provider", config.utility_provider.model_dump(exclude_none=True))
    if config.voice is not None:
        add_section("voice", config.voice.model_dump(exclude_none=True))
    if config.node is not None:
        add_section("node", config.node.model_dump(exclude_none=True))
    if config.character is not None:
        entries["character"] = config.character
    return entries


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
    return VoiceService(
        stt=stt,
        tts=tts,
        lipsync_fps=config.lipsync_fps,
        tts_timeout_retries=config.tts.timeout_retries if config.tts else 2,
        tts_retry_backoff_s=config.tts.retry_backoff_s if config.tts else 0.5,
    )


def _resolve_memory_backend(config: MemoryConfig, *, has_character: bool) -> str:
    if config.backend != "auto":
        return config.backend
    return "file" if has_character else "none"


class Waifu:
    """
    組裝根（Composition Root）：將所有元件以 DI 方式組合

    不含業務邏輯，只負責建立依賴關係並串接資料流
    """

    def __init__(
        self,
        config: WaifuConfig,
        paths: Optional[AppPaths] = None,
        localmode: Optional[bool] = False,
        gateway_config_service: Optional[GatewayConfigService] = None,
    ) -> None:
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
        self._voice_service: Optional[VoiceService] = _build_voice_service(config.voice)

        # Hook
        self._hook_registry = HookRegistry()
        self._hook_pipeline = HookPipeline(self._hook_registry)
        self._memory_hook: Optional[MemoryHook] = None
        self._register_builtin_hooks(config)

        # Agent
        self._context_builder = ContextBuilder(config.context, hook_registry=self._hook_registry)
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

        self._plugin_manager = PluginManager(
            hook_registry=self._hook_registry,
            plugin_registry=self._plugin_registry,
            store=self._conversation_store,
            sessions=self._gateway.session_manager,
            gateway=self._gateway,
            gateway_config_service=gateway_config_service,
            voice=self._voice_service,
        )
        self._gateway.set_dispatch_handler(self._dispatch)

        # Plugin Loader
        self._plugin_loader = PluginLoader(self._paths.plugins_dir)

        # Repositories
        self._cron_store = CronStore()
        self._register_builtin_tools()
        self._plugin_repo = PluginRepository()
        self._config_repo = AppConfigRepository()
        self._character_repo = CharacterRepository()
        self._relationship_repo = RelationshipRepository()

        # config.toml is the source of truth; mirror its snapshot into DB.
        self._config_repo.replace_all(_config_seed(config))

        self._card_parser = CardParser()
        self._card_importer = CardImporter(cards_dir=self._paths.cards_dir, parser=self._card_parser)

        # Services
        self._plugin_service = PluginService(self._plugin_repo, self._plugin_manager, self._plugin_loader)
        self._mcp_service = MCPService(self._mcp_manager, self._paths.mcp_config_file)
        self._skill_service = SkillService(self._skill_registry, self._paths.skills_dir)
        self._config_service = AppConfigService(self._config_repo, self._context_builder, self._agent_runner)
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
            memory_clear=self._memory_hook.clear if self._memory_hook is not None else None,
        )
        self._gateway.set_command_service(self._command_service)
        self._character_service = CharacterService(
            self._character_repo,
            self._relationship_repo,
            manager=self._character_manager,
            card_importer=self._card_importer,
        )
        self._token_analytics = TokenAnalyticsRepository()

        self._cron_executor = CronExecutor(dispatch_fn=self._dispatch)
        self._cron_scheduler = CronScheduler(store=self._cron_store, executor=self._cron_executor)

        import functools

        self._heartbeat_manager = HeartbeatManager(dispatch_fn=functools.partial(self._dispatch, skip_auto_title=True))

    def _register_builtin_hooks(self, config: WaifuConfig) -> None:
        """根據 config 自動掛載內建 hooks"""
        memory_store = None
        backend = _resolve_memory_backend(config.memory, has_character=bool(config.character))
        logger.info(
            "Memory backend resolved to '{}' (configured='{}', character_configured={})",
            backend,
            config.memory.backend,
            bool(config.character),
        )
        if config.memory.backend == "auto" and backend == "file":
            logger.info("Auto memory backend selected 'file'; set memory.backend='history_tree' to enable HistoryTree")
        if backend == "file":
            memory_store = FileMemoryStore(
                memory_dir=self._paths.memory_dir,
                character_name=config.character,
                max_recent=config.context.max_history_messages,
                share_direct_memories=config.memory.file.share_direct_memories,
            )
        elif backend == "history_tree":
            memory_store = HistoryTreeStore(
                base_url=config.memory.history_tree.base_url,
                timeout_s=config.memory.history_tree.timeout_s,
                top_k=config.memory.history_tree.top_k,
                rerank=config.memory.history_tree.rerank,
                query_graph=config.memory.history_tree.query_graph,
                ingest_graph=config.memory.history_tree.ingest_graph,
                character_name=config.character,
            )

        memory_hook = MemoryHook(
            store=memory_store,
            max_history=config.context.max_history_messages,
        )
        self._memory_hook = memory_hook
        self._hook_registry.register(memory_hook)
        emohook = EmotionHook()
        self._hook_registry.register(emohook)
        if self._voice_service is not None and self._voice_service.has_tts:
            self._hook_registry.register(TTSHook(self._voice_service, emohook))
        self._hook_registry.register(LoggingHook())

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
        """掛載 Gateway Adapter（WebSocket / Discord / Telegram / HTTP）"""
        self._gateway.mount(adapter)
        from waifu.gateway.adapters.waifu_node import WaifuNodeAdapter
        from waifu.gateway.adapters.websocket import WebSocketAdapter

        if isinstance(adapter, WaifuNodeAdapter):
            self._node_manager.wire(adapter)
        if isinstance(adapter, WebSocketAdapter):
            adapter.set_heartbeat_manager(self._heartbeat_manager)
        return self

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
        self._collect_capabilities()
        self._import_cards_on_startup()
        await self._restore_persistent_state()
        await self._cron_scheduler.start()
        if not self._localmode:
            await self._gateway.start()

    async def stop(self) -> None:
        """停止 Scheduler 與 Gateway"""
        await self._cron_scheduler.stop()
        await self._gateway.stop()

    def _collect_capabilities(self) -> None:
        """收集所有 hook/plugin 的 capabilities 寫入 GatewayCore"""
        for hook in self._hook_registry.hooks:
            caps = getattr(hook, "capabilities", None)
            if isinstance(caps, dict):
                self._gateway.capabilities.update(caps)

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
        reply_fn: Optional[Any] = None,
    ) -> OutgoingResponse:
        if isinstance(request, MessageParts):
            request = request.to_request(
                conversation_id=conversation_id,
                reply_fn=reply_fn,
            )
        return await self._dispatch(request)

    @property
    def started_at(self) -> float:
        return self._started_at

    async def _dispatch(self, request: IncomingRequest, *, skip_auto_title: bool = False) -> OutgoingResponse:
        """
        完整請求生命週期：
          Session → HookPipeline.pre → ContextBuilder → AgentRunner
          → HookPipeline.post → OutgoingResponse
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
            self._conversation_store.create_with_id(
                request.conversation_id,
                title=request.conversation_id,
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

        agent_result = await self._run_agent(ctx, system_prompt, tools, context_manager)
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
        new_waifu_msgs = [_to_waifu_message(m) for m in context_manager.history[history_len:]]

        ctx.new_messages = new_waifu_msgs
        ctx = await self._hook_pipeline.run_mid(ctx)

        session.add_messages(ctx.new_messages)
        self._persist_new_messages(request.conversation_id, ctx.new_messages, agent_result.trace.token_usage)

        ctx = await self._hook_pipeline.run_post(ctx)

        display_content = _EMOTION_TAG_RE.sub("", ctx.response or final_content).strip()

        # title 仍等於 conversation_id 代表還未命名 → 背景生成標題並推送給前端
        conv = self._conversation_store.get(request.conversation_id)
        if conv is not None and str(conv.title) == request.conversation_id and final_content and not skip_auto_title:
            asyncio.create_task(
                self._auto_title(
                    request.conversation_id,
                    request.content,
                    final_content,
                    reply_fn=request.reply_fn,
                )
            )

        return self._build_response(request, content=display_content, ctx=ctx)

    async def _run_agent(self, ctx: HookContext, system_prompt: str, tools: Any, context_manager: Any) -> Any:
        request = ctx.request
        try:
            return await self._agent_runner.run(ctx, system_prompt, tools, context_manager)
        except asyncio.CancelledError:
            logger.warning(
                "Request {} cancelled (client disconnected), writing interrupt placeholder",
                request.request_id,
            )
            self._conversation_store.add_llm_message(
                request.conversation_id,
                {"role": "assistant", "content": "〔已中斷〕"},
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

    def _persist_new_messages(self, conversation_id: str, new_messages: list, usage: Any) -> None:
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

    async def _auto_title(
        self,
        conversation_id: str,
        user_msg: str,
        assistant_reply: str,
        *,
        reply_fn: Any,
    ) -> None:
        import inspect

        title = await self._utility_ai.generate_title(user_msg, assistant_reply)
        if not title:
            return

        self._conversation_store.update_title(conversation_id, title)
        logger.info("Auto-titled conversation {} → '{}'", conversation_id[:8], title)

        event = {
            "event": "title_update",
            "data": {"conversation_id": conversation_id, "title": title},
        }
        try:
            if inspect.iscoroutinefunction(reply_fn):
                await reply_fn(event=event)
            else:
                reply_fn(event=event)
        except Exception:
            logger.debug("title_update event could not be delivered (connection closed?)")

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
            reply_fn=request.reply_fn,
        )
