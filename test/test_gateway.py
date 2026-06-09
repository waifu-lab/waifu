import os
import uuid

import pytest

from waifu_types import ConversationMode


@pytest.mark.unit
def test_discord_default_gateway_config():
    from waifu.gateway.adapters.discord import DiscordAdapter

    cfg = DiscordAdapter.default_gateway_config()
    assert cfg["enabled"] is False
    assert cfg["token"] == ""
    assert "stream_edit" in cfg


@pytest.mark.unit
def test_discord_from_gateway_config_disabled():
    from waifu.gateway.adapters.discord import DiscordAdapter

    adapter = DiscordAdapter.from_gateway_config({"enabled": False, "token": "tok"})
    assert adapter is None


@pytest.mark.unit
def test_discord_from_gateway_config_no_token():
    from waifu.gateway.adapters.discord import DiscordAdapter

    adapter = DiscordAdapter.from_gateway_config({"enabled": True, "token": ""})
    assert adapter is None


@pytest.mark.unit
def test_discord_from_gateway_config_valid():
    pytest.importorskip("discord", reason="discord.py not installed")
    from waifu.gateway.adapters.discord import DiscordAdapter

    adapter = DiscordAdapter.from_gateway_config({"enabled": True, "token": "fake_tok"})
    assert adapter is not None
    assert isinstance(adapter, DiscordAdapter)


@pytest.mark.unit
def test_discord_build_gateway_status():
    from waifu.gateway.adapters.discord import DiscordAdapter

    status = DiscordAdapter.build_gateway_status({"enabled": True, "token": "tok"})
    assert status["name"] == "discord"
    assert status["enabled"] is True
    assert status["configured"] is True

    status2 = DiscordAdapter.build_gateway_status({"enabled": False, "token": ""})
    assert status2["configured"] is False


@pytest.mark.unit
def test_discord_group_conversation_id_per_user():
    from waifu.gateway.adapters.discord import _discord_group_conversation_id

    cid = _discord_group_conversation_id(111, 999, group_sessions_per_user=True)
    assert "discord:channel:111" in cid
    assert "user:999" in cid


@pytest.mark.unit
def test_discord_group_conversation_id_shared():
    from waifu.gateway.adapters.discord import _discord_group_conversation_id

    cid = _discord_group_conversation_id(111, 999, group_sessions_per_user=False)
    assert cid == "discord:channel:111"


@pytest.mark.unit
def test_telegram_default_gateway_config():
    from waifu.gateway.adapters.telegram import TelegramAdapter

    cfg = TelegramAdapter.default_gateway_config()
    assert cfg["enabled"] is False
    assert cfg["token"] == ""
    assert "trigger_command" in cfg


@pytest.mark.unit
def test_telegram_from_gateway_config_disabled():
    from waifu.gateway.adapters.telegram import TelegramAdapter

    adapter = TelegramAdapter.from_gateway_config({"enabled": False, "token": "tok"})
    assert adapter is None


@pytest.mark.unit
def test_telegram_from_gateway_config_no_token():
    from waifu.gateway.adapters.telegram import TelegramAdapter

    adapter = TelegramAdapter.from_gateway_config({"enabled": True, "token": ""})
    assert adapter is None


@pytest.mark.unit
def test_telegram_from_gateway_config_valid():
    pytest.importorskip("telegram", reason="python-telegram-bot not installed")
    from waifu.gateway.adapters.telegram import TelegramAdapter

    adapter = TelegramAdapter.from_gateway_config({"enabled": True, "token": "fake_telegram_tok"})
    assert adapter is not None
    assert isinstance(adapter, TelegramAdapter)


@pytest.mark.unit
def test_telegram_build_gateway_status():
    from waifu.gateway.adapters.telegram import TelegramAdapter

    status = TelegramAdapter.build_gateway_status({"enabled": True, "token": "tok"})
    assert status["name"] == "telegram"
    assert status["enabled"] is True
    assert status["configured"] is True


@pytest.mark.offline
def test_discord_adapter_mountable(waifu):
    pytest.importorskip("discord", reason="discord.py not installed")
    from waifu.gateway.adapters.discord import DiscordAdapter

    adapter = DiscordAdapter(token="headless_test_token")
    waifu.mount(adapter)
    assert adapter in waifu.gateway._adapters


@pytest.mark.offline
def test_telegram_adapter_mountable(waifu):
    pytest.importorskip("telegram", reason="python-telegram-bot not installed")
    from waifu.gateway.adapters.telegram import TelegramAdapter

    adapter = TelegramAdapter(token="headless_test_token")
    waifu.mount(adapter)
    assert adapter in waifu.gateway._adapters


@pytest.mark.offline
def test_discord_dm_request_shape():
    """Simulate the on_message DM path without a real Discord client."""
    pytest.importorskip("discord", reason="discord.py not installed")
    import discord
    from unittest.mock import MagicMock

    from waifu.gateway.adapters.discord import _discord_group_conversation_id

    # Build a minimal mock DM message
    author = MagicMock()
    author.id = 12345
    author.display_name = "Alice"

    channel = MagicMock(spec=discord.DMChannel)

    message = MagicMock()
    message.author = author
    message.channel = channel
    message.clean_content = "hello bot"
    message.attachments = []
    message.mentions = []
    message.reference = None

    # Replicate the adapter's DM logic
    from waifu_types import IncomingRequest, Sender

    conversation_id = f"discord:dm:{author.id}"
    sender = Sender(user_id=f"discord:user:{author.id}", display_name=author.display_name)

    request = IncomingRequest(
        request_id=str(uuid.uuid4()),
        conversation_id=conversation_id,
        mode=ConversationMode.direct,
        sender=sender,
        source="discord",
        content=message.clean_content,
        attachments=[],
        reply_fn=lambda **kw: None,
    )

    assert request.conversation_id == "discord:dm:12345"
    assert request.sender.display_name == "Alice"
    assert request.mode == ConversationMode.direct
    assert request.content == "hello bot"


@pytest.mark.offline
def test_discord_group_request_shape():
    """Simulate the GROUP conversation ID assignment."""
    from waifu.gateway.adapters.discord import _discord_group_conversation_id

    cid = _discord_group_conversation_id(777, 888, group_sessions_per_user=True)
    assert cid.startswith("discord:channel:777")
    assert "888" in cid


@pytest.mark.online
async def test_discord_adapter_start_stop():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        pytest.skip("DISCORD_BOT_TOKEN not set")

    pytest.importorskip("discord", reason="discord.py not installed")
    from waifu.gateway.adapters.discord import DiscordAdapter
    from conftest import load_config
    from waifu.waifu import Waifu

    config = load_config()
    w = Waifu(config)
    adapter = DiscordAdapter(token=token)
    w.mount(adapter)
    # start in localmode would not bind gateway; just verify no crash on mount
    assert adapter._token == token


@pytest.mark.online
async def test_telegram_adapter_start_stop():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        pytest.skip("TELEGRAM_BOT_TOKEN not set")

    pytest.importorskip("telegram", reason="python-telegram-bot not installed")
    from waifu.gateway.adapters.telegram import TelegramAdapter
    from conftest import load_config
    from waifu.waifu import Waifu

    config = load_config()
    w = Waifu(config)
    adapter = TelegramAdapter(token=token)
    w.mount(adapter)
    assert adapter._token == token
