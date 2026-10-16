from abc import ABC
from typing import Any, Dict, List, Optional, Sequence, Set

from pydantic import BaseModel, ConfigDict, Field

from waifu_types.output import OutputTransformer
from waifu_types.prompt import SystemPromptLayers
from waifu_types.session import BaseSession
from waifu_types.trace import BaseExecutionTrace
from waifu_types.types import BaseMessage, Event, IncomingRequest


class HookContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    request: IncomingRequest
    session: BaseSession
    messages: List[BaseMessage]  # 可被 hook 修改的對話歷史
    metadata: Dict[str, Any] = Field(default_factory=dict)  # 本輪 hook 間自由使用的暫存
    response: Optional[str] = None  # post hook 時有值（原始 LLM 輸出，未經 OutputTransformer）
    trace: Optional[BaseExecutionTrace] = None
    events: List[Event] = Field(default_factory=list)  # 隨最終回應送出的事件
    abort: bool = False  # True 則跳過 Agent
    new_messages: List[BaseMessage] = Field(default_factory=list)  # 本輪新訊息，mid hook 可修改後再存入 history
    handled: Set[str] = Field(default_factory=set)
    """本輪已被某個 hook 處理的功能（例如 TTSHook 已逐句送出情緒時加入 "emotion"），讓其他 hook 避免重複處理"""

    def emit(self, event: "Event | Dict[str, Any]") -> None:
        """加入一個隨最終回應送出的事件；需要即時送出請用 request.reply_event()"""
        self.events.append(Event.coerce(event))


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

    def contribute_prompt(self, ctx: HookContext, layers: SystemPromptLayers) -> None:  # noqa: ARG002
        """新增片段到 system prompt 的特定層。"""
        return None

    def output_transformers(self) -> Sequence[OutputTransformer]:
        """此 hook 提供的輸出處理器"""
        return ()

    def capabilities(self) -> Dict[str, Any]:
        """WebSocket 連線時回報給前端的能力描述"""
        return {}
