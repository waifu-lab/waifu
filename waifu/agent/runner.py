from typing import TYPE_CHECKING

from shuvi.agent import Agent
from shuvi.types import AgentCallbacks, AgentConfig, AgentResult
from waifu_types import HookContext

from .context import AgentInput

if TYPE_CHECKING:
    from hai.providers.providers import ProviderText


class AgentRunner:
    """
    包裝 shuvi.Agent，注入 streaming callback

    使用 DI：ProviderText 由外部（Waifu）注入
    """

    def __init__(self, provider: "ProviderText") -> None:
        self._provider = provider

    async def run(self, ctx: HookContext, agent_input: AgentInput) -> AgentResult:
        agent = Agent(
            AgentConfig(
                provider=self._provider,
                system_prompt=agent_input.system_prompt,
                tools=agent_input.tools,
                callbacks=AgentCallbacks(
                    # streaming：每個 assistant chunk 即時推送給 client
                    assistant_message=lambda msg: ctx.request.reply_fn(chunk=msg.get("content", "")),
                ),
                session_id=ctx.request.conversation_id,
            )
        )
        return await agent.run(agent_input.messages)
