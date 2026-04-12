from .http import HTTPAdapter
from .websocket import WebSocketAdapter

__all__ = ["WebSocketAdapter", "HTTPAdapter", "DiscordAdapter", "TelegramAdapter"]


def __getattr__(name: str) -> object:
    if name == "DiscordAdapter":
        from .discord import DiscordAdapter

        return DiscordAdapter
    if name == "TelegramAdapter":
        from .telegram import TelegramAdapter

        return TelegramAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
