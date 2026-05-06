import logging
import inspect
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Literal, Optional

from shuvi.agent import Agent
from shuvi.context import ContextManager
from shuvi.types import AGENT_OUTCOME, AgentCallbacks, AgentConfig, AgentResult
from waifu_types import HookContext

if TYPE_CHECKING:
    from hai.providers.providers import ProviderText
    from hai.tool import Tool

logger = logging.getLogger(__name__)

_MAX_RETRIES = 1

_EMOTION_COMPLETE = re.compile(r"\[emotion:\w+\]", re.IGNORECASE)
# FIXME: 待修改 — 這個 partial regex 太醜，應改成通用串流 tag 緩衝器
_EMOTION_PARTIAL = re.compile(
    r"\[(?:e(?:m(?:o(?:t(?:i(?:o(?:n(?::(?:\w+)?)?)?)?)?)?)?)?)?$",
    re.IGNORECASE,
)


class _EmotionStripper:
    """串流時緩衝並剝除 [emotion:xxx] tag，避免原始標籤送到前端。"""

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, chunk: str) -> str:
        self._buf += chunk
        self._buf = _EMOTION_COMPLETE.sub("", self._buf)
        m = _EMOTION_PARTIAL.search(self._buf)
        if m:
            out, self._buf = self._buf[: m.start()], self._buf[m.start() :]
        else:
            out, self._buf = self._buf, ""
        return out

    def flush(self) -> str:
        out, self._buf = self._buf, ""
        return out


@dataclass
class QueryState:
    """跨 request 的 per-conversation 執行狀態。"""

    turn_count: int = 0
    consecutive_failures: int = 0
    last_outcome: Optional[str] = None
    transition: Literal["running", "done", "failed", "recovering"] = "done"
    # token 估算
    last_input_tokens: int = 0
    last_output_tokens: int = 0


class AgentRunner:
    def __init__(self, provider: "ProviderText") -> None:
        self.provider = provider
        # per-conversation 狀態，鍵為 conversation_id
        self._states: Dict[str, QueryState] = {}

    def get_state(self, conversation_id: str) -> QueryState:
        if conversation_id not in self._states:
            self._states[conversation_id] = QueryState()
        return self._states[conversation_id]

    async def run(
        self,
        ctx: HookContext,
        system_prompt: str,
        tools: List["Tool"],
        context_manager: ContextManager,
    ) -> AgentResult:
        stripper = _EmotionStripper()

        async def _on_chunk(chunk: str) -> None:
            clean = stripper.feed(chunk)
            if not clean:
                return
            fn = ctx.request.reply_fn
            if inspect.iscoroutinefunction(fn):
                await fn(chunk=clean)
            else:
                fn(chunk=clean)

        cid = ctx.request.conversation_id
        state = self.get_state(cid)
        state.transition = "running"

        last_exc: Optional[BaseException] = None

        for attempt in range(_MAX_RETRIES + 1):
            captured_exc: Optional[BaseException] = None

            def _on_error(e: Exception) -> None:
                nonlocal captured_exc
                captured_exc = e

            agent = Agent(
                AgentConfig(
                    provider=self.provider,
                    system_prompt=system_prompt,
                    tools=tools,
                    callbacks=AgentCallbacks(on_chunk=_on_chunk, error=_on_error),
                    session_id=cid,
                    context_manager=context_manager,
                )
            )

            result = await agent.run()

            remaining = stripper.flush()
            if remaining:
                fn = ctx.request.reply_fn
                if inspect.iscoroutinefunction(fn):
                    await fn(chunk=remaining)
                else:
                    fn(chunk=remaining)

            if result.outcome == AGENT_OUTCOME.error:
                last_exc = captured_exc
                state.consecutive_failures += 1
                state.transition = "recovering" if attempt < _MAX_RETRIES else "failed"
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        "AgentRunner: attempt %d/%d failed (%s), retrying…",
                        attempt + 1,
                        _MAX_RETRIES + 1,
                        last_exc,
                    )
                    continue
                state.last_outcome = AGENT_OUTCOME.error.value
                raise RuntimeError(f"Agent failed after {_MAX_RETRIES + 1} attempt(s)") from last_exc

            state.consecutive_failures = 0
            state.last_outcome = result.outcome.value
            state.transition = "done"
            state.turn_count += result.trace.inner_iterations
            state.last_input_tokens = result.trace.token_usage.input
            state.last_output_tokens = result.trace.token_usage.output

            ctx.metadata["query_state"] = state

            return result

        raise RuntimeError("AgentRunner: unexpected exit from retry loop")
