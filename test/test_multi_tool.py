import pytest

from conftest import make_request


@pytest.mark.unit
def test_read_write_tools_available(waifu):
    tools = {t.name: t for t in waifu.plugin_registry.get_all_tools()}
    assert "read" in tools
    assert "write" in tools
    assert "shell" in tools


@pytest.mark.unit
def test_write_then_read_directly(tmp_dir):
    """Write → read pipeline works at the function level (no LLM)."""
    from waifu.tool.read import read_tool
    from waifu.tool.write import write_tool

    dest = tmp_dir / "chain_test.txt"
    write_tool.func(path=str(dest), content="chain_payload")
    assert "chain_payload" in dest.read_text(encoding="utf-8")

    read_result = read_tool.func(path=str(dest))
    assert "chain_payload" in read_result


@pytest.mark.online
async def test_write_then_read_chain(waifu, tmp_dir):
    """Agent writes a file then reads it back — requires two tool calls."""
    dest = tmp_dir / "agent_chain.txt"
    req = make_request(
        f"Please do the following in order:\n"
        f"1. Use the write tool to write the text 'hello_chain_verify' to: {dest}\n"
        f"2. Use the read tool to read back that file.\n"
        f"3. Tell me the file contents."
    )
    response = await waifu._dispatch(req)
    assert "hello_chain_verify" in response.content
    assert dest.exists()


@pytest.mark.online
async def test_shell_then_read_chain(waifu, tmp_dir):
    """Agent runs a shell command that creates a file, then reads it."""
    dest = tmp_dir / "shell_out.txt"
    req = make_request(
        f"Use the shell tool to run: echo shell_chain_ok > {dest}\n"
        f"Then use the read tool to read {dest} and tell me its contents."
    )
    response = await waifu._dispatch(req)
    assert dest.exists()
    assert "shell_chain_ok" in response.content or "shell_chain_ok" in dest.read_text(encoding="utf-8", errors="ignore")


@pytest.mark.online
async def test_three_tool_chain(waifu, tmp_dir):
    """Agent chains write → read → shell in a single request."""
    data_file = tmp_dir / "three_chain.txt"

    req = make_request(
        f"Please do this sequence with tools:\n"
        f"1. write 'three_tools_test' to {data_file}\n"
        f"2. read {data_file} to confirm the content\n"
        f"3. use shell tool: python -c \"print(open(r'{data_file}').read().strip().upper())\" "
        f"   and tell me the uppercase version."
    )
    response = await waifu._dispatch(req)
    assert "THREE_TOOLS_TEST" in response.content.upper()


@pytest.mark.online
async def test_file_search_chain(waifu, tmp_dir):
    """Agent uses file_search to find a file it just wrote."""
    target = tmp_dir / "findme_unique9x.txt"
    target.write_text("findme content", encoding="utf-8")

    req = make_request(
        f"Use the file_search tool to search for files matching 'findme_unique9x' in {tmp_dir}, "
        f"then read the found file and tell me its content."
    )
    response = await waifu._dispatch(req)
    assert "findme content" in response.content
