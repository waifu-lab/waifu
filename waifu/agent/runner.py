from typing import TYPE_CHECKING, Any, List, Optional

from shuvi.agent import Agent
from shuvi.context import ContextManager
from shuvi.types import AGENT_OUTCOME, AgentCallbacks, AgentConfig, AgentResult

from waifu_types import Event, HookContext, StreamObserver, StreamTransform

if TYPE_CHECKING:
    from hai.providers.providers import ProviderText
    from hai.tool import Tool

from waifu.logger import logger


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
        observer: StreamObserver,
    ) -> AgentResult:
        request = ctx.request
        turn_sent = 0

        async def _on_chunk(chunk: str) -> None:
            nonlocal turn_sent
            observer.feed(chunk)
            clean = stream.feed(chunk)
            if clean:
                turn_sent += len(clean)
                await request.reply_chunk(clean)

        async def _on_stream_reset(partial: str) -> None:
            nonlocal turn_sent
            stream.flush()
            observer.reset()
            discard, turn_sent = turn_sent, 0
            logger.warning("Stream interrupted after {} chars, re-running the turn", len(partial))
            await request.reply_event(Event(event="stream_reset", data={"discard": discard}))

        def _on_turn_end(_state: Any) -> None:
            nonlocal turn_sent
            turn_sent = 0
            observer.end_turn()

        async def _on_tool_error(tool_name: str, exc: Exception) -> None:
            logger.warning("Tool '{}' raised an error: {}", tool_name, exc)
            await request.reply_event(Event(event="tool_error", data={"name": tool_name, "error": str(exc)}))

        async def _on_tool_call(tool_name: str, arguments: str) -> None:
            await request.reply_event(Event(event="tool_call", data={"name": tool_name, "arguments": arguments}))

        async def _on_tool_result(tool_name: str, result: str) -> None:
            await request.reply_event(Event(event="tool_result", data={"name": tool_name, "result": result}))

        cid = request.conversation_id
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
                    on_stream_reset=_on_stream_reset,
                    state_update=_on_turn_end,
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

        if result.outcome == AGENT_OUTCOME.error:
            raise RuntimeError(f"Agent failed for conversation {cid}") from captured_exc
        return result
