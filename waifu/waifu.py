from typing import Any, Dict, Optional

from hai.providers.providers import ProviderSTT, ProviderText, ProviderTTS
from waifu.agent import AgentRunner, ContextBuilder
from waifu.config import ProviderConfig, VoiceConfig, WaifuConfig
from waifu.gateway import GatewayCore
from waifu.hook import HookPipeline, HookRegistry
from waifu.hook.builtin import EmotionHook, LoggingHook, MemoryHook, TTSHook
from waifu.plugin import PluginManager, PluginRegistry
from waifu.store import AppPaths, Database
from waifu.store.conversation import ConversationStore
from waifu.voice import VoiceService
from waifu_types import BaseGatewayAdapter, BaseHook, BasePlugin, HookContext, IncomingRequest, OutgoingResponse


def _build_provider(config: "ProviderConfig") -> ProviderText:
    """從 ProviderConfig 建立 ProviderText 實例"""
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
        # Store — resolve paths and initialise DB (idempotent)
        self._paths = paths or AppPaths.resolve()
        self._db = Database(self._paths.db_file)
        self._db.init()
        self._conversation_store = ConversationStore(conversations_dir=self._paths.conversations_dir)

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
        self._plugin_manager = PluginManager(
            hook_registry=self._hook_registry,
            plugin_registry=self._plugin_registry,
            store=self._conversation_store,
            sessions=self._gateway.session_manager,
            gateway=self._gateway,
            voice=self._voice_service,
        )
        self._gateway.set_dispatch_handler(self._dispatch)

    def _register_builtin_hooks(self, config: WaifuConfig) -> None:
        """根據 config 自動掛載內建 hooks"""
        self._hook_registry.register(
            MemoryHook(
                max_history=config.context.max_history_messages,
            )
        )
        self._hook_registry.register(EmotionHook())
        if self._voice_service is not None and self._voice_service.has_tts:
            self._hook_registry.register(TTSHook(self._voice_service))
        self._hook_registry.register(LoggingHook())

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
        """啟動所有已掛載的 Adapter"""
        await self._gateway.start()

    @property
    def gateway(self) -> GatewayCore:
        return self._gateway

    @property
    def plugin_manager(self) -> PluginManager:
        return self._plugin_manager

    @property
    def voice_service(self) -> Optional[VoiceService]:
        return self._voice_service

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
