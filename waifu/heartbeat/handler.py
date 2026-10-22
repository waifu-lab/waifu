import inspect
import random
import uuid
from abc import ABC, abstractmethod
from typing import Awaitable, Callable, List

from waifu.logger import logger
from waifu_types import (
    ConversationMode,
    Feature,
    IncomingRequest,
    OutgoingResponse,
    ReplyFn,
    RequestMeta,
    Sender,
    SessionMeta,
)

DispatchFn = Callable[[IncomingRequest], Awaitable[OutgoingResponse]]


class HeartbeatHandler(ABC):
    @abstractmethod
    async def handle(
        self,
        event_name: str,
        data: dict,
        session_token: str,
        conversation_id: str,
        reply_fn: ReplyFn,
    ) -> None: ...


class GreetingPoolHandler(HeartbeatHandler):
    """從問候池隨機挑一句直接推送，不消耗 token。"""

    def __init__(self, pool: List[str]) -> None:
        self._pool = pool

    async def handle(
        self,
        event_name: str,
        _data: dict,
        _session_token: str,
        conversation_id: str,
        reply_fn: ReplyFn,
    ) -> None:
        if not self._pool:
            return
        msg = random.choice(self._pool)
        response = OutgoingResponse(
            request_id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            source="heartbeat",
            content=msg,
        )
        result = reply_fn(response)
        if inspect.isawaitable(result):
            await result
        logger.debug("Heartbeat [{}] → greeting pool: {!r}", event_name, msg)


class LLMHandler(HeartbeatHandler):
    """呼叫 LLM 生成個性化回應並推送給用戶（含 TTS）；每次使用獨立的暫時對話。"""

    def __init__(self, dispatch_fn: DispatchFn, prompt: str) -> None:
        self._dispatch = dispatch_fn
        self._prompt = prompt

    async def handle(
        self,
        event_name: str,
        data: dict,
        session_token: str,
        _conversation_id: str,
        reply_fn: ReplyFn,
    ) -> None:
        metadata: dict = {RequestMeta.SKIP_AUTO_TITLE: True}
        expressions = data.get(SessionMeta.LIVE2D_EXPRESSIONS)
        if expressions:
            # 新對話建立時 request.metadata 會複製進 session.metadata
            metadata[SessionMeta.LIVE2D_EXPRESSIONS] = expressions
        request = IncomingRequest(
            request_id=str(uuid.uuid4()),
            conversation_id=f"heartbeat:{uuid.uuid4()}",
            mode=ConversationMode.session,
            sender=Sender(user_id=f"ws:{session_token}", display_name="User"),
            source="heartbeat",
            content=self._prompt,
            features={Feature.LIVE2D},
            metadata=metadata,
            reply_fn=reply_fn,
        )
        logger.debug("Heartbeat [{}] → LLM dispatch conv={}", event_name, request.conversation_id)
        await self._dispatch(request)
