from abc import ABC
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from .types import IncomingRequest


class HookContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    request: IncomingRequest
    session: Any  # waifu.gateway.session.Session
    messages: List[Dict[str, Any]]  # 可被 hook 修改的對話歷史
    metadata: Dict[str, Any] = {}
    response: Optional[str] = None  # post hook 時有值
    trace: Optional[Any] = None  # shuvi.ExecutionTrace
    events: List[Dict[str, Any]] = []  # 副作用（EmotionHook 寫入）
    abort: bool = False  # True 則跳過 Agent


class BaseHook(ABC):
    name: str
    priority: int = 0  # 數字越小越先執行

    async def pre(self, ctx: HookContext) -> HookContext:
        return ctx

    async def post(self, ctx: HookContext) -> HookContext:
        return ctx
