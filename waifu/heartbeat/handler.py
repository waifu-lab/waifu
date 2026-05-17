import random
import uuid
from abc import ABC, abstractmethod
from typing import Callable, Coroutine, List, Optional

from waifu.logger import logger
from waifu_types import ConversationMode, IncomingRequest, OutgoingResponse, Sender


class HeartbeatHandler(ABC):
    @abstractmethod
    async def handle(
        self,
        event_name: str,
        data: dict,
        session_token: str,
        conversation_id: str,
        push_fn: Callable[[str], Coroutine],
    ) -> None: ...


class GreetingPoolHandler(HeartbeatHandler):
    """從問候池隨機挑一句直接推送，不消耗 token。"""

    def __init__(self, pool: List[str]) -> None:
        self._pool = pool

    async def handle(
        self,
        event_name: str,
        data: dict,
        session_token: str,
        conversation_id: str,
        push_fn: Callable[[str], Coroutine],
    ) -> None:
        msg = random.choice(self._pool)
        await push_fn(msg)
        logger.debug("Heartbeat [{}] → greeting pool: {!r}", event_name, msg)


class LLMHandler(HeartbeatHandler):
    """呼叫 LLM 生成個性化回應，結果寫進主對話並推送給用戶。"""

    def __init__(
        self,
        dispatch_fn: Callable[[IncomingRequest], Coroutine[None, None, OutgoingResponse]],
        prompt: str,
    ) -> None:
        self._dispatch = dispatch_fn
        self._prompt = prompt

    async def handle(
        self,
        event_name: str,
        data: dict,
        session_token: str,
        conversation_id: str,
        push_fn: Callable[[str], Coroutine],
    ) -> None:
        request = IncomingRequest(
            request_id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            mode=ConversationMode.session,
            sender=Sender(user_id=f"ws:{session_token}", display_name="User"),
            source="heartbeat",
            content=self._prompt,
            reply_fn=_make_reply_fn(push_fn),
        )
        logger.debug("Heartbeat [{}] → LLM dispatch conv={}", event_name, conversation_id)
        await self._dispatch(request)


def _make_reply_fn(push_fn: Callable[[str], Coroutine]):
    async def reply_fn(
        response: Optional[OutgoingResponse] = None,
        *,
        chunk: Optional[str] = None,
        event: Optional[dict] = None,
    ) -> None:
        if response is not None and response.content:
            await push_fn(response.content)

    return reply_fn
