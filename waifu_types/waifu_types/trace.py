from typing import Any, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class TokenUsage(Protocol):
    @property
    def input(self) -> int: ...
    @property
    def output(self) -> int: ...
    @property
    def total(self) -> int: ...


@runtime_checkable
class BaseExecutionTrace(Protocol):
    start_time: str
    end_time: str
    duration_ms: float
    @property
    def token_usage(self) -> TokenUsage: ...
    inner_iterations: int
    outer_retries: int
    outcome: Any  # shuvi.types.AGENT_OUTCOME
    tool_calls: List[Any]
    verifications: List[Any]
    session_id: Optional[str]
