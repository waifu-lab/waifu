from typing import TYPE_CHECKING, Any

from ._version import __version__

if TYPE_CHECKING:
    from .config import WaifuConfig
    from .waifu import Waifu


def __getattr__(name: str) -> Any:
    if name == "Waifu":
        from .waifu import Waifu

        return Waifu
    if name == "WaifuConfig":
        from .config import WaifuConfig

        return WaifuConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["Waifu", "WaifuConfig", "__version__"]
