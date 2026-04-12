from importlib.metadata import PackageNotFoundError, version

from .config import WaifuConfig
from .waifu import Waifu

try:
    __version__: str = version("waifu")
except PackageNotFoundError:
    __version__ = "0.0.0+dev"

__all__ = ["Waifu", "WaifuConfig", "__version__"]
