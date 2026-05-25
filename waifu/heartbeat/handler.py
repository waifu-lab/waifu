import random
import uuid
from abc import ABC, abstractmethod
from typing import Callable, Coroutine, List

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
        _conversation_id: str,
        push_fn: Callable[[str], Coroutine],
    ) -> None:
        request = IncomingRequest(
            request_id=str(uuid.uuid4()),
            conversation_id=f"heartbeat:{uuid.uuid4()}",
            mode=ConversationMode.session,
            sender=Sender(user_id=f"ws:{session_token}", display_name="User"),
            source="heartbeat",
            content=self._prompt,
            reply_fn=_noop,
        )
        logger.debug("Heartbeat [{}] → LLM dispatch conv={}", event_name, request.conversation_id)
        response = await self._dispatch(request)
        if response and response.content:
            await push_fn(response.content)


async def _noop(*args, **kwargs) -> None:
    pass
