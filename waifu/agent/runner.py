from typing import TYPE_CHECKING, List

from shuvi.agent import Agent
from shuvi.context import ContextManager
from shuvi.types import AgentCallbacks, AgentConfig, AgentResult
from waifu_types import HookContext

if TYPE_CHECKING:
    from hai.providers.providers import ProviderText
    from hai.tool import Tool


class AgentRunner:
    def __init__(self, provider: "ProviderText") -> None:
        self.provider = provider

    async def run(
        self,
        ctx: HookContext,
        system_prompt: str,
        tools: List["Tool"],
        context_manager: ContextManager,
    ) -> AgentResult:
        agent = Agent(
            AgentConfig(
                provider=self.provider,
                system_prompt=system_prompt,
                tools=tools,
                callbacks=AgentCallbacks(
                    assistant_message=lambda msg: ctx.request.reply_fn(chunk=msg.content or ""),
                ),
                session_id=ctx.request.conversation_id,
                context_manager=context_manager,
            )
        )
        return await agent.run()
