from abc import ABC, abstractmethod
from typing import Any, Dict, List

from waifu_types.tool import ToolLike


class BaseMCPAdapter(ABC):
    @abstractmethod
    async def connect(self) -> None:
        """連線至外部 MCP Server"""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """斷開連線，釋放資源"""
        ...

    @abstractmethod
    async def list_tools(self) -> List[ToolLike]:
        """回傳此 MCP Server 提供的 Tool"""
        ...

    @abstractmethod
    async def call_tool(self, name: str, args: Dict[str, Any]) -> str:
        """呼叫指定工具，回傳字串結果"""
        ...
