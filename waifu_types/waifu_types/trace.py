from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class BaseExecutionTrace(Protocol):
    start_time: str
    end_time: str
    duration_ms: float
    token_usage: Dict[str, int]
    inner_iterations: int
    outer_retries: int
    outcome: Any  # shuvi.types.AGENT_OUTCOME
    tool_calls: List[Any]
    verifications: List[Any]
    session_id: Optional[str]
