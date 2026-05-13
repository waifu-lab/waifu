from importlib.metadata import PackageNotFoundError, version

try:
    __version__: str = version("waifu")
except PackageNotFoundError:
    __version__ = "0.0.0+dev"

from .config import WaifuConfig  # noqa: E402
from .waifu import Waifu  # noqa: E402

__all__ = ["Waifu", "WaifuConfig", "__version__"]
