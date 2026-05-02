from abc import ABC
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from waifu_types.session import BaseSession
from waifu_types.trace import BaseExecutionTrace
from waifu_types.types import BaseMessage, IncomingRequest


class HookContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    request: IncomingRequest
    session: BaseSession
    messages: List[BaseMessage]  # 可被 hook 修改的對話歷史
    metadata: Dict[str, Any] = {}
    response: Optional[str] = None  # post hook 時有值
    trace: Optional[BaseExecutionTrace] = None
    events: List[Dict[str, Any]] = []  # 副作用（EmotionHook 寫入）
    abort: bool = False  # True 則跳過 Agent
    new_messages: List[BaseMessage] = []  # 本輪新產生的訊息，mid hook 可修改，存入 history 前使用


class BaseHook(ABC):
    name: str
    priority: int = 0  # 數字越小越先執行

    async def pre(self, ctx: HookContext) -> HookContext:
        return ctx

    async def mid(self, ctx: HookContext) -> HookContext:
        """在 agent 生成完、存入 history/DB 之前執行。可修改 ctx.new_messages。"""
        return ctx

    async def post(self, ctx: HookContext) -> HookContext:
        return ctx

    def system_prompt_fragment(self, ctx: HookContext) -> Optional[str]:  # noqa: ARG002
        """回傳要注入 system prompt 的片段，None 表示不注入。"""
        return None
