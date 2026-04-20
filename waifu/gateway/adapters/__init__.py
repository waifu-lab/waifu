from typing import TYPE_CHECKING

from .http import HTTPAdapter
from .websocket import WebSocketAdapter
from .waifu_node import WaifuNodeAdapter

if TYPE_CHECKING:
    from .discord import DiscordAdapter
    from .telegram import TelegramAdapter

__all__ = ["WebSocketAdapter", "HTTPAdapter", "WaifuNodeAdapter", "DiscordAdapter", "TelegramAdapter"]


def __getattr__(name: str) -> object:
    if name == "DiscordAdapter":
        from .discord import DiscordAdapter

        return DiscordAdapter
    if name == "TelegramAdapter":
        from .telegram import TelegramAdapter

        return TelegramAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
