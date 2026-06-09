import asyncio
import uuid

import pytest

from waifu.cron.executor import CronExecutor
from waifu.store.models import CronJob


def _make_job(**kwargs) -> CronJob:
    """Build an unsaved in-memory CronJob (peewee model, no DB required)."""
    defaults = dict(
        id=str(uuid.uuid4()),
        name=f"test_job_{uuid.uuid4().hex[:8]}",
        type="every",
        schedule="1h",
        command="echo unit_test",
        kind="shell",
        enabled=True,
        target_conversation_id=None,
        sender_user_id=None,
        sender_display_name=None,
    )
    defaults.update(kwargs)
    return CronJob(**defaults)


@pytest.mark.unit
async def test_executor_shell_echo():
    async def noop_dispatch(req):
        raise AssertionError("dispatch should not be called in shell mode")

    executor = CronExecutor(dispatch_fn=noop_dispatch)
    job = _make_job(command="echo shell_cron_ok", kind="shell")
    output = await executor.execute(job)
    assert "shell_cron_ok" in output


@pytest.mark.unit
async def test_executor_shell_nonzero_raises():
    executor = CronExecutor(dispatch_fn=lambda req: (_ for _ in ()).throw(AssertionError()))
    job = _make_job(command="exit 1", kind="shell")
    with pytest.raises(RuntimeError, match="shell exited"):
        await executor.execute(job)


@pytest.mark.unit
async def test_executor_llm_dispatches_request():
    """LLM-mode cron job calls dispatch_fn with the job's command as content."""
    received: list = []

    from waifu_types import OutgoingResponse

    async def fake_dispatch(req):
        received.append(req)
        return OutgoingResponse(
            request_id=req.request_id,
            conversation_id=req.conversation_id,
            source=req.source,
            content="llm_cron_dispatched",
            reply_fn=lambda **kw: None,
        )

    executor = CronExecutor(dispatch_fn=fake_dispatch)
    job = _make_job(command="what time is it?", kind="llm")
    result = await executor.execute(job)

    assert len(received) == 1
    assert received[0].content == "what time is it?"
    assert received[0].source == "cron"
    assert result == "llm_cron_dispatched"


@pytest.mark.unit
async def test_executor_llm_uses_target_conversation():
    from waifu_types import OutgoingResponse

    received: list = []

    async def fake_dispatch(req):
        received.append(req)
        return OutgoingResponse(
            request_id=req.request_id,
            conversation_id=req.conversation_id,
            source=req.source,
            content="ok",
            reply_fn=lambda **kw: None,
        )

    executor = CronExecutor(dispatch_fn=fake_dispatch)
    job = _make_job(
        command="ping",
        kind="llm",
        target_conversation_id="conv:test:99",
        sender_user_id="user:42",
        sender_display_name="Scheduler",
    )
    await executor.execute(job)
    assert received[0].conversation_id == "conv:test:99"
    assert received[0].sender.user_id == "user:42"


@pytest.mark.offline
def test_cron_tool_create_and_list(waifu):
    """Create a cron job via the cron tool func, then list it."""
    tools = {t.name: t for t in waifu.plugin_registry.get_all_tools()}
    cron = tools.get("cron")
    assert cron is not None, "'cron' tool missing from registry"

    job_name = f"ci_test_{uuid.uuid4().hex[:6]}"
    create_result = cron.func(
        action="create",
        name=job_name,
        schedule_type="every",
        schedule="1h",
        command="echo offline_cron",
        kind="shell",
    )
    assert "[ok]" in create_result, create_result

    list_result = cron.func(action="list")
    assert job_name in list_result

    # cleanup
    cron.func(action="delete", name=job_name)


@pytest.mark.offline
def test_cron_tool_delete(waifu):
    tools = {t.name: t for t in waifu.plugin_registry.get_all_tools()}
    cron = tools["cron"]

    job_name = f"ci_del_{uuid.uuid4().hex[:6]}"
    cron.func(action="create", name=job_name, schedule_type="every", schedule="2h", command="echo x")
    del_result = cron.func(action="delete", name=job_name)
    assert "[ok]" in del_result

    list_result = cron.func(action="list")
    assert job_name not in list_result


@pytest.mark.offline
def test_cron_tool_enable_disable(waifu):
    tools = {t.name: t for t in waifu.plugin_registry.get_all_tools()}
    cron = tools["cron"]

    job_name = f"ci_toggle_{uuid.uuid4().hex[:6]}"
    cron.func(action="create", name=job_name, schedule_type="every", schedule="1h", command="echo t")

    assert "[ok]" in cron.func(action="disable", name=job_name)
    assert "[ok]" in cron.func(action="enable", name=job_name)

    cron.func(action="delete", name=job_name)


@pytest.mark.offline
def test_cron_tool_invalid_action(waifu):
    tools = {t.name: t for t in waifu.plugin_registry.get_all_tools()}
    cron = tools["cron"]
    result = cron.func(action="fly")
    assert "error" in result.lower()


@pytest.mark.online
async def test_agent_creates_cron_job(waifu):
    from conftest import make_request

    job_name = f"agent_cron_{uuid.uuid4().hex[:6]}"
    req = make_request(
        f"Use the cron tool to create a new cron job with:\n"
        f"  name: {job_name}\n"
        f"  schedule_type: every\n"
        f"  schedule: 30m\n"
        f"  command: echo agent_cron_test\n"
        f"  kind: shell\n"
        f"Then call cron list and tell me if the job was created."
    )
    response = await waifu._dispatch(req)
    assert job_name in response.content or "[ok]" in response.content

    # cleanup directly
    tools = {t.name: t for t in waifu.plugin_registry.get_all_tools()}
    tools["cron"].func(action="delete", name=job_name)


@pytest.mark.online
async def test_agent_lists_cron_jobs(waifu):
    from conftest import make_request

    req = make_request("Use the cron tool with action='list' and report what cron jobs exist.")
    response = await waifu._dispatch(req)
    assert response.content.strip() != ""
