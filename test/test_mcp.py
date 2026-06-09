from typing import Any, Dict, List

import pytest

from waifu_types import BaseMCPAdapter


class FakeMCPAdapter(BaseMCPAdapter):
    """Minimal in-process MCP adapter that exposes a single 'echo' tool."""

    connected = False

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def list_tools(self) -> list:
        from hai.tool import Tool

        return [
            Tool(
                name="mcp_echo",
                description="Echoes the input message back with a prefix.",
                parameters={
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "Text to echo."},
                    },
                    "required": ["message"],
                },
                func=lambda message: f"[mcp_echo] {message}",
            )
        ]

    async def call_tool(self, name: str, args: Dict[str, Any]) -> str:
        if name == "mcp_echo":
            return f"[mcp_echo] {args.get('message', '')}"
        return f"[error] unknown tool: {name}"


@pytest.mark.unit
async def test_mcp_manager_add_registers_tools(waifu):
    mgr = waifu.mcp_manager
    adapter = FakeMCPAdapter()
    await mgr.add("fake_server", adapter)

    assert "fake_server" in mgr.list()
    assert adapter.connected

    tools = waifu.plugin_registry.get_all_tools()
    names = [t.name for t in tools]
    assert "mcp_echo" in names

    # cleanup
    await mgr.remove("fake_server")


@pytest.mark.unit
async def test_mcp_manager_remove_deregisters_tools(waifu):
    mgr = waifu.mcp_manager
    adapter = FakeMCPAdapter()
    await mgr.add("fake_rm", adapter)
    await mgr.remove("fake_rm")

    assert "fake_rm" not in mgr.list()
    assert not adapter.connected

    tools = waifu.plugin_registry.get_all_tools()
    names = [t.name for t in tools]
    assert "mcp_echo" not in names


@pytest.mark.unit
async def test_mcp_manager_duplicate_name_raises(waifu):
    mgr = waifu.mcp_manager
    a1 = FakeMCPAdapter()
    a2 = FakeMCPAdapter()
    await mgr.add("dup_server", a1)
    with pytest.raises(ValueError, match="already registered"):
        await mgr.add("dup_server", a2)
    await mgr.remove("dup_server")


@pytest.mark.unit
async def test_mcp_manager_remove_nonexistent_noop(waifu):
    mgr = waifu.mcp_manager
    await mgr.remove("does_not_exist")  # should not raise


@pytest.mark.offline
async def test_mcp_tool_callable_directly(waifu):
    """The MCP echo tool returns the expected string when called directly."""
    mgr = waifu.mcp_manager
    adapter = FakeMCPAdapter()
    await mgr.add("direct_call", adapter)

    tools = {t.name: t for t in waifu.plugin_registry.get_all_tools()}
    echo_tool = tools.get("mcp_echo")
    assert echo_tool is not None

    import asyncio

    result = echo_tool.func(message="hello_offline")
    if asyncio.iscoroutine(result):
        result = await result
    assert "hello_offline" in result

    await mgr.remove("direct_call")


@pytest.mark.online
async def test_agent_calls_mcp_tool(waifu):
    """Agent discovers mcp_echo tool and calls it with the correct argument."""
    from conftest import make_request

    mgr = waifu.mcp_manager
    adapter = FakeMCPAdapter()
    await mgr.add("agent_fake", adapter)

    try:
        req = make_request("Use the mcp_echo tool to echo the message 'mcp_integration_ok' and tell me the result.")
        response = await waifu._dispatch(req)
        assert "mcp_integration_ok" in response.content
    finally:
        await mgr.remove("agent_fake")
