import asyncio
import subprocess
import uuid
from typing import TYPE_CHECKING, Callable, Coroutine, Optional

from waifu.logger import logger
from waifu_types import ConversationMode, Event, IncomingRequest, OutgoingResponse, Sender

if TYPE_CHECKING:
    from waifu.store.models import CronJob


class CronExecutor:
    def __init__(
        self,
        dispatch_fn: Callable[[IncomingRequest], Coroutine[None, None, OutgoingResponse]],
    ) -> None:
        self._dispatch = dispatch_fn

    async def execute(self, job: "CronJob") -> str:
        kind = str(job.kind)
        if kind == "llm":
            return await self._execute_llm(job)
        return await self._execute_shell(job)

    async def _execute_shell(self, job: "CronJob") -> str:
        result = await asyncio.to_thread(
            subprocess.run,
            str(job.command),
            shell=True,
            capture_output=True,
            text=True,
        )
        output = (result.stdout + result.stderr).strip()
        if result.returncode != 0:
            raise RuntimeError(f"shell exited {result.returncode}: {output}")
        return output

    async def _execute_llm(self, job: "CronJob") -> str:
        conversation_id: str = str(job.target_conversation_id or f"cron:{job.id}")
        user_id: str = str(job.sender_user_id or f"cron:{job.id}")
        display_name: str = str(job.sender_display_name or "Scheduler")

        request = IncomingRequest(
            request_id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            mode=ConversationMode.direct,
            sender=Sender(user_id=user_id, display_name=display_name),
            source="cron",
            content=str(job.command),
            reply_fn=_noop_reply,
        )

        logger.debug("CronJob {!r}: dispatching LLM request conv={}", job.name, conversation_id)
        response = await self._dispatch(request)
        return response.content or ""


async def _noop_reply(
    response: Optional[OutgoingResponse] = None,
    *,
    chunk: Optional[str] = None,
    event: Optional[Event] = None,
) -> None:
    """離線情況的 reply_fn：結果已由 _dispatch 寫入 DB，無需即時推送。"""
    pass
