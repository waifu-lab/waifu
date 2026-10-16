from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol, Sequence

from waifu_types.types import IncomingRequest


@dataclass(frozen=True)
class CommandArgument:
    name: str
    description: str
    required: bool = False


@dataclass(frozen=True)
class CommandDefinition:
    name: str
    description: str
    arguments: tuple[CommandArgument, ...] = ()


CommandHandler = Callable[[IncomingRequest, str], Awaitable[str]]
"""(request, args) -> 回覆文字"""


class CommandCatalog(Protocol):
    """供 adapter 註冊平台原生指令（Discord slash / Telegram command）"""

    @property
    def definitions(self) -> Sequence[CommandDefinition]: ...
