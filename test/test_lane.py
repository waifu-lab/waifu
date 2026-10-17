import asyncio

import pytest

from waifu_types import ConversationMode, IncomingRequest, OutgoingResponse, Sender


def _request(conversation_id: str, content: str, replies: list) -> IncomingRequest:
    async def reply_fn(response=None, *, chunk=None, event=None):  # noqa: ARG001
        if response is not None:
            replies.append(response.content)

    return IncomingRequest(
        conversation_id=conversation_id,
        mode=ConversationMode.session,
        sender=Sender(user_id="u", display_name="U"),
        source="test",
        content=content,
        reply_fn=reply_fn,
    )


def _core_with_handler(handler):
    from waifu.gateway.core import GatewayCore

    core = GatewayCore()
    core.set_dispatch_handler(handler)
    return core


@pytest.mark.unit
async def test_same_conversation_is_serial_and_lane_released():
    running = 0
    max_running = 0

    async def handler(req: IncomingRequest) -> OutgoingResponse:
        nonlocal running, max_running
        running += 1
        max_running = max(max_running, running)
        await asyncio.sleep(0.01)
        running -= 1
        return OutgoingResponse(
            request_id=req.request_id, conversation_id=req.conversation_id, source="t", content=req.content
        )

    core = _core_with_handler(handler)
    replies: list = []
    # 一個走 adapter 式的 dispatch，兩個走 dispatch_and_wait（cron / heartbeat / SDK）
    await core.dispatch(_request("c1", "a", replies))
    results = await asyncio.gather(
        core.dispatch_and_wait(_request("c1", "b", replies)),
        core.dispatch_and_wait(_request("c1", "c", replies)),
    )

    assert [r.content for r in results] == ["b", "c"]
    assert replies == ["a", "b", "c"]
    assert max_running == 1
    await asyncio.sleep(0)
    assert len(core._lane_manager) == 0


@pytest.mark.unit
async def test_dispatch_and_wait_propagates_error_and_lane_continues():
    async def handler(req: IncomingRequest) -> OutgoingResponse:
        if req.content == "boom":
            raise ValueError("boom")
        return OutgoingResponse(
            request_id=req.request_id, conversation_id=req.conversation_id, source="t", content="ok"
        )

    core = _core_with_handler(handler)
    replies: list = []
    with pytest.raises(ValueError):
        await core.dispatch_and_wait(_request("c1", "boom", replies))
    ok = await core.dispatch_and_wait(_request("c1", "fine", replies))
    assert ok.content == "ok"
    assert replies == ["ok"]


@pytest.mark.unit
async def test_reply_helpers_accept_sync_and_async_reply_fn():
    from waifu_types import Event

    seen: list = []
    req = IncomingRequest(
        conversation_id="c",
        mode=ConversationMode.session,
        sender=Sender(user_id="u", display_name="U"),
        source="test",
        content="x",
        reply_fn=lambda response=None, **kw: seen.append(kw or response),
    )
    await req.reply_chunk("hi")
    await req.reply_event({"event": "emotion", "data": {"emotion": "happy"}})
    assert seen[0] == {"chunk": "hi"}
    assert seen[1] == {"event": Event(event="emotion", data={"emotion": "happy"})}


@pytest.mark.unit
def test_legacy_live2d_flags_become_features():
    from waifu_types import Feature

    req = IncomingRequest(
        conversation_id="c",
        mode=ConversationMode.session,
        sender=Sender(user_id="u", display_name="U"),
        source="test",
        content="x",
        live2d=True,
        need_lipsync=True,
        reply_fn=lambda **_: None,
    )
    assert req.features == {Feature.LIVE2D, Feature.LIPSYNC}


@pytest.mark.unit
async def test_interrupt_cancels_current_request_and_lane_continues():
    started = asyncio.Event()
    cancelled: list = []

    async def handler(req: IncomingRequest) -> OutgoingResponse:
        if req.content == "slow":
            started.set()
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.append(req.content)
                raise
        return OutgoingResponse(
            request_id=req.request_id, conversation_id=req.conversation_id, source="t", content=req.content
        )

    core = _core_with_handler(handler)
    replies: list = []
    slow = _request("c1", "slow", replies)
    await core.dispatch(slow)
    await core.dispatch(_request("c1", "next", replies))
    await started.wait()

    interrupted = await core.interrupt("c1")
    assert interrupted is slow
    assert cancelled == ["slow"]

    after = await core.dispatch_and_wait(_request("c1", "after", replies))
    assert after.content == "after"
    assert replies == ["next", "after"]
    assert await core.interrupt("c1") is None
