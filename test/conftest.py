import tempfile
import uuid
from pathlib import Path

import pytest

from waifu_types import ConversationMode, IncomingRequest, Sender


def load_config():
    from waifu.store import AppPaths

    paths = AppPaths.resolve()
    config_path = paths.config_file
    if not config_path.exists():
        pytest.skip(f"config.toml not found at {config_path} — skipping online test")

    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    from waifu.config import WaifuConfig

    return WaifuConfig(**data)


@pytest.fixture(scope="module")
def waifu_config():
    """Load real WaifuConfig from config.toml. Skips if file absent."""
    return load_config()


@pytest.fixture(scope="module")
def isolated_paths():
    from waifu.store import AppPaths

    with tempfile.TemporaryDirectory() as d:
        paths = AppPaths(data_dir=Path(d) / "data", config_dir=Path(d) / "config")
        paths.ensure_dirs()
        yield paths


@pytest.fixture(scope="module")
async def waifu(waifu_config, isolated_paths):
    """Headless Waifu instance (no gateway adapters). Shared within a module."""
    from waifu.waifu import Waifu

    w = Waifu(waifu_config, paths=isolated_paths)
    yield w


@pytest.fixture(scope="module")
async def waifu_started(waifu_config, isolated_paths):
    """Waifu with start() called (loads MCP, plugins, cron). localmode=True skips gateway bind."""
    from waifu.waifu import Waifu

    w = Waifu(waifu_config, paths=isolated_paths, localmode=True)
    await w.start()
    yield w
    await w.stop()


@pytest.fixture()
def tmp_dir():
    """Cross-platform temp directory that bypasses pytest's base-temp-dir logic.

    Use this instead of pytest's built-in `tmp_path` on Windows where
    pytest-asyncio (asyncio_mode=auto) can cause a WinError 5 (Access Denied)
    when wrapping the `tmp_path` fixture setup.
    """
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def make_request(
    content: str,
    *,
    conversation_id: str | None = None,
    user_id: str = "test-user",
    display_name: str = "Tester",
    source: str = "test",
) -> IncomingRequest:
    """Build a minimal IncomingRequest for headless _dispatch() calls."""
    chunks: list = []
    return IncomingRequest(
        conversation_id=conversation_id or f"test:{uuid.uuid4()}",
        mode=ConversationMode.session,
        sender=Sender(user_id=user_id, display_name=display_name),
        source=source,
        content=content,
        reply_fn=lambda *_, **kw: chunks.append(kw.get("chunk", "")),
    )
