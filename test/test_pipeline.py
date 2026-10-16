import uuid
from types import SimpleNamespace

import pytest

from waifu_types import (
    AssistantMessage,
    BaseHook,
    BasePlugin,
    CommandDefinition,
    ConversationMode,
    Feature,
    HookContext,
    IncomingRequest,
    PluginContext,
    RequestMeta,
    Sender,
    SessionMeta,
    tool,
)

RAW_REPLY = "[emotion:happy]你好！[emotion:sad]掰掰"
CHUNKS = ["[emo", "tion:happy]你好", "！[emotion:sa", "d]掰掰"]


@pytest.fixture()
def waifu(tmp_dir):
    from waifu.config import ProviderConfig, WaifuConfig
    from waifu.store import AppPaths
    from waifu.waifu import Waifu

    paths = AppPaths(data_dir=tmp_dir / "data", config_dir=tmp_dir / "config")
    paths.ensure_dirs()
    config = WaifuConfig(provider=ProviderConfig(provider="openai", api_key="sk-test", model="test-model"))
    w = Waifu(config, paths=paths, localmode=True)

    calls: list = []

    async def fake_run(ctx, system_prompt, tools, context_manager, stream):
        calls.append(SimpleNamespace(system_prompt=system_prompt, tools=[t.name for t in tools]))
        for chunk in CHUNKS:
            out = stream.feed(chunk)
            if out:
                await ctx.request.reply_chunk(out)
        rest = stream.flush()
        if rest:
            await ctx.request.reply_chunk(rest)
        msg = AssistantMessage(content=RAW_REPLY)
        context_manager.append(msg)
        trace = SimpleNamespace(
            start_time="",
            end_time="",
            duration_ms=0.0,
            token_usage=SimpleNamespace(input=3, output=4, total=7),
            inner_iterations=1,
            outer_retries=0,
            outcome=None,
            tool_calls=[],
            verifications=[],
            session_id=None,
        )
        return SimpleNamespace(messages=[msg], trace=trace)

    w._agent_runner.run = fake_run  # type: ignore[method-assign]
    w.agent_calls = calls  # type: ignore[attr-defined]
    return w


class Collector:
    def __init__(self) -> None:
        self.chunks: list = []
        self.events: list = []
        self.responses: list = []

    async def __call__(self, response=None, *, chunk=None, event=None):
        if chunk is not None:
            self.chunks.append(chunk)
        elif event is not None:
            self.events.append(event)
        elif response is not None:
            self.responses.append(response)


def _request(content: str, reply: Collector, *, features=(), conversation_id=None) -> IncomingRequest:
    return IncomingRequest(
        conversation_id=conversation_id or f"test:{uuid.uuid4()}",
        mode=ConversationMode.session,
        sender=Sender(user_id="tester", display_name="Tester"),
        source="test",
        content=content,
        features=set(features),
        metadata={RequestMeta.SKIP_AUTO_TITLE: True},
        reply_fn=reply,
    )


@pytest.mark.offline
async def test_emotion_tags_stripped_everywhere(waifu):
    reply = Collector()
    req = _request("嗨", reply, features=[Feature.LIVE2D])
    response = await waifu.dispatch(req)

    assert "".join(reply.chunks) == "你好！掰掰"
    assert all("[" not in c for c in reply.chunks)
    assert response.content == "你好！掰掰"
    assert reply.responses == [response]
    assert [e.data["emotion"] for e in response.events if e.event == "emotion"] == ["happy", "sad"]
    assert "情緒表達" in waifu.agent_calls[0].system_prompt

    stored = waifu.conversation_store.get_llm_messages(req.conversation_id, limit=0)
    assert stored[-1]["role"] == "assistant"
    assert stored[-1]["content"] == "你好！掰掰"
    session = waifu.gateway.session_manager.get(req.conversation_id)
    assert session.history[-1].content == "你好！掰掰"


@pytest.mark.offline
async def test_without_live2d_no_emotion_prompt_or_events(waifu):
    reply = Collector()
    response = await waifu.dispatch(_request("嗨", reply))

    assert response.content == "你好！掰掰"
    assert response.events == []
    assert "情緒表達" not in waifu.agent_calls[0].system_prompt


@pytest.mark.offline
async def test_system_prompt_dynamic_parts_only_at_end(waifu):
    """每輪變動的資訊集中在結尾，前綴固定以利 provider prompt cache"""
    await waifu.dispatch(_request("嗨", Collector()))
    other = _request("嗨", Collector())
    other.sender = Sender(user_id="someone-else", display_name="Other")
    await waifu.dispatch(other)

    first, second = (c.system_prompt for c in waifu.agent_calls)
    marker = "## Current Context"
    assert first.count(marker) == 1 and first.rstrip().endswith(first[first.index(marker) :].rstrip())
    assert first[: first.index(marker)] == second[: second.index(marker)]
    assert "tester" not in first[: first.index(marker)]


@pytest.mark.offline
async def test_builtin_prompt_can_be_disabled(waifu):
    waifu.config_service.set("context.builtin_prompt", False)
    await waifu.dispatch(_request("嗨", Collector()))
    assert "anime-style companion" not in waifu.agent_calls[0].system_prompt


class _MarkHook(BaseHook):
    name = "mark"
    priority = 40

    def contribute_prompt(self, ctx: HookContext, layers) -> None:  # noqa: ARG002
        layers.user_custom.append("PLUGIN_MARK")


@tool
async def plugin_echo(text: str) -> str:
    """回傳輸入文字"""
    return text


class _DemoPlugin(BasePlugin):
    name = "demo"

    async def on_load(self, ctx: PluginContext) -> None:
        ctx.register_hook(_MarkHook())
        ctx.register_tool(plugin_echo)

        async def ping(request: IncomingRequest, args: str) -> str:  # noqa: ARG001
            return f"pong {args}".strip()

        ctx.register_command(CommandDefinition("ping", "Ping"), ping)


@pytest.mark.offline
async def test_plugin_disable_enable_unload(waifu):
    await waifu.plugin(_DemoPlugin())

    def state():
        return (
            any(h.name == "mark" for h in waifu._hook_registry.hooks),
            waifu.plugin_registry.get_tool("plugin_echo") is not None,
            "ping" in [d.name for d in waifu._command_service.definitions],
        )

    assert state() == (True, True, True)
    pong = await waifu.dispatch(_request("/ping hi", Collector()))
    assert pong.content == "pong hi"
    assert waifu.agent_calls == []

    await waifu.plugin_manager.disable("demo")
    assert state() == (False, False, False)
    await waifu.dispatch(_request("hello", Collector()))
    assert "PLUGIN_MARK" not in waifu.agent_calls[-1].system_prompt
    assert "plugin_echo" not in waifu.agent_calls[-1].tools

    await waifu.plugin_manager.enable("demo")
    assert state() == (True, True, True)
    await waifu.dispatch(_request("hello", Collector()))
    assert "PLUGIN_MARK" in waifu.agent_calls[-1].system_prompt
    assert "plugin_echo" in waifu.agent_calls[-1].tools

    await waifu.plugin_manager.unload("demo")
    assert state() == (False, False, False)
    # 內建工具不受影響
    assert waifu.plugin_registry.get_tool("read") is not None


@pytest.mark.offline
async def test_heartbeat_goes_through_gateway_and_filters_expressions(waifu):
    reply = Collector()
    await waifu.heartbeat_manager.dispatch("pet", {SessionMeta.LIVE2D_EXPRESSIONS: ["happy"]}, "tok", "tok", reply)

    assert len(reply.responses) == 1
    response = reply.responses[0]
    assert response.content == "你好！掰掰"
    assert [e.data["emotion"] for e in response.events] == ["happy"]
    # heartbeat 對話不自動命名
    conv = waifu.conversation_store.get(response.conversation_id)
    assert str(conv.title) == response.conversation_id


def _titling_request(reply: Collector, conversation_id: str) -> IncomingRequest:
    req = _request("嗨", reply, conversation_id=conversation_id)
    req.metadata = {}
    return req


@pytest.mark.offline
async def test_auto_title_generates_once_and_notifies(waifu):
    calls: list = []

    async def fake_title(user: str, reply: str) -> str:
        calls.append((user, reply))
        return "打招呼"

    waifu._utility_ai.generate_title = fake_title
    reply = Collector()
    cid = f"test:{uuid.uuid4()}"
    await waifu.dispatch(_titling_request(reply, cid))
    await waifu._auto_title.wait_idle()
    await waifu.dispatch(_titling_request(reply, cid))
    await waifu._auto_title.wait_idle()

    assert calls == [("嗨", "你好！掰掰")]  # 標籤已移除；第二輪不再命名
    assert str(waifu.conversation_store.get(cid).title) == "打招呼"
    assert [e.data["title"] for e in reply.events if e.event == "title_update"] == ["打招呼"]


@pytest.mark.offline
async def test_auto_title_does_not_override_user_rename(waifu):
    import asyncio

    release = asyncio.Event()

    async def slow_title(user: str, reply: str) -> str:  # noqa: ARG001
        await release.wait()
        return "自動標題"

    waifu._utility_ai.generate_title = slow_title
    cid = f"test:{uuid.uuid4()}"
    await waifu.dispatch(_titling_request(Collector(), cid))
    waifu.conversation_store.update_title(cid, "我的標題")  # 命名期間使用者改名
    release.set()
    await waifu._auto_title.wait_idle()
    assert str(waifu.conversation_store.get(cid).title) == "我的標題"


@pytest.mark.offline
async def test_auto_title_retries_are_bounded(waifu):
    calls: list = []

    async def failing_title(user: str, reply: str) -> str:  # noqa: ARG001
        calls.append(user)
        return ""

    waifu._utility_ai.generate_title = failing_title
    cid = f"test:{uuid.uuid4()}"
    for _ in range(5):
        await waifu.dispatch(_titling_request(Collector(), cid))
        await waifu._auto_title.wait_idle()
    assert len(calls) == waifu._auto_title.MAX_ATTEMPTS
    assert waifu.conversation_store.needs_auto_title(cid)


@pytest.mark.offline
async def test_unknown_platform_command_lists_available(waifu):
    reply = Collector()
    req = _request("/nope", reply)
    req.platform_command = "nope"
    response = await waifu.dispatch(req)
    assert response.content.startswith("Unknown command: /nope")
    assert waifu.agent_calls == []
