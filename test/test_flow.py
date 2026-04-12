"""
之後刪除
"""

import uuid

import pytest

from waifu.plugin.builtin import ToolPlugin
from waifu.store import AppPaths
from waifu.tool.read import read_tool
from waifu.tool.shell import shell_tool
from waifu.tool.webfetch import webfetch_tool
from waifu.tool.write import write_tool
from waifu.waifu import Waifu
from waifu_types import ConversationMode, IncomingRequest
from waifu_types.types import Sender


def _load_config():
    """從 AppPaths 找到 config.toml 並解析"""
    paths = AppPaths.resolve()
    config_path = paths.config_file
    if not config_path.exists():
        pytest.skip(f"config not found: {config_path}")

    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    from waifu.config import WaifuConfig

    return WaifuConfig(**data)


@pytest.fixture(scope="module")
def config():
    return _load_config()


@pytest.fixture(scope="module")
async def waifu(config):
    """建立真實 Waifu 實例，掛載所有基礎工具"""
    w = Waifu(config)
    await w.plugin(ToolPlugin("basic", [read_tool, write_tool, shell_tool, webfetch_tool]))
    return w


def make_request(content: str) -> IncomingRequest:
    chunks = []
    return IncomingRequest(
        conversation_id=f"test:{uuid.uuid4()}",
        mode=ConversationMode.session,
        sender=Sender(user_id="test-user", display_name="Tester"),
        source="test",
        content=content,
        reply_fn=lambda **kw: chunks.append(kw.get("chunk", "")),
    )


@pytest.mark.asyncio
async def test_plain_qa(waifu):
    """基本問答，不需要工具"""
    req = make_request("請用一句話回答：1 + 1 等於多少？")
    response = await waifu._dispatch(req)

    assert response.content.strip() != ""
    assert "2" in response.content


@pytest.mark.asyncio
async def test_tool_read(waifu, tmp_path):
    """讓 LLM 讀取一個測試檔案，驗證 read tool 被正確呼叫"""
    test_file = tmp_path / "secret.txt"
    test_file.write_text("waifu_read_ok", encoding="utf-8")

    req = make_request(f"請使用 read 工具讀取這個檔案並告訴我裡面的內容：{test_file}")
    response = await waifu._dispatch(req)

    assert "waifu_read_ok" in response.content


@pytest.mark.asyncio
async def test_tool_write(waifu, tmp_path):
    """讓 LLM 寫入一個檔案，驗證 write tool 被正確呼叫且檔案存在"""
    dest = tmp_path / "waifu_out.txt"

    req = make_request(f"請使用 write 工具將文字 'hello_from_waifu' 寫入這個路徑：{dest}")
    response = await waifu._dispatch(req)

    assert dest.exists(), "write tool 沒有建立檔案"
    assert "hello_from_waifu" in dest.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_tool_shell(waifu):
    """讓 LLM 執行 shell 指令，驗證 shell tool 回傳結果"""
    req = make_request("請使用 shell 工具執行 'echo waifu_shell_test'，並告訴我輸出結果")
    response = await waifu._dispatch(req)

    assert "waifu_shell_test" in response.content
