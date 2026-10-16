from typing import TYPE_CHECKING, List, Optional

from shuvi.agent import Agent
from shuvi.context import ContextManager
from shuvi.types import AGENT_OUTCOME, AgentCallbacks, AgentConfig, AgentResult
from waifu_types import Event, HookContext, StreamTransform

if TYPE_CHECKING:
    from hai.providers.providers import ProviderText
    from hai.tool import Tool

from waifu.logger import logger

_MAX_RETRIES = 1


class AgentRunner:
    def __init__(self, provider: "ProviderText") -> None:
        self.provider = provider

    async def run(
        self,
        ctx: HookContext,
        system_prompt: str,
        tools: List["Tool"],
        context_manager: ContextManager,
        stream: StreamTransform,
    ) -> AgentResult:
        request = ctx.request
        emitted = False

        async def _on_chunk(chunk: str) -> None:
            nonlocal emitted
            emitted = True
            clean = stream.feed(chunk)
            if clean:
                await request.reply_chunk(clean)

        async def _on_tool_error(tool_name: str, exc: Exception) -> None:
            logger.warning("Tool '{}' raised an error: {}", tool_name, exc)
            await request.reply_event(Event(event="tool_error", data={"name": tool_name, "error": str(exc)}))

        async def _on_tool_call(tool_name: str, arguments: str) -> None:
            nonlocal emitted
            emitted = True
            await request.reply_event(Event(event="tool_call", data={"name": tool_name, "arguments": arguments}))

        async def _on_tool_result(tool_name: str, result: str) -> None:
            await request.reply_event(Event(event="tool_result", data={"name": tool_name, "result": result}))

        cid = request.conversation_id
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
                    callbacks=AgentCallbacks(
                        on_chunk=_on_chunk,
                        error=_on_error,
                        on_tool_error=_on_tool_error,
                        tool_call=_on_tool_call,
                        tool_result=_on_tool_result,
                    ),
                    session_id=cid,
                    context_manager=context_manager,
                )
            )

            result = await agent.run()

            remaining = stream.flush()
            if remaining:
                await request.reply_chunk(remaining)

            if result.outcome != AGENT_OUTCOME.error:
                return result

            last_exc = captured_exc
            if attempt < _MAX_RETRIES and not emitted:
                logger.warning(
                    "AgentRunner: attempt {}/{} failed ({}), retrying…",
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    last_exc,
                )
                continue
            break

        raise RuntimeError(f"Agent failed for conversation {cid}") from last_exc
