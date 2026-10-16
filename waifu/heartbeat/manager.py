from typing import Dict, List, Optional

from waifu.config import HeartbeatEventConfig
from waifu.heartbeat.handler import DispatchFn, GreetingPoolHandler, HeartbeatHandler, LLMHandler
from waifu.logger import logger
from waifu_types import ReplyFn

DEFAULT_EVENTS: List[HeartbeatEventConfig] = [
    HeartbeatEventConfig(
        event_name="active",
        kind="llm",
        prompt="使用者回到電腦前了，請自然地打個招呼。",
    ),
    HeartbeatEventConfig(
        event_name="pet",
        kind="llm",
        prompt="使用者剛剛摸了你，請用可愛的方式回應這個互動。",
    ),
]


class HeartbeatManager:
    """非用戶主動觸發的事件"""

    def __init__(
        self,
        dispatch_fn: DispatchFn,
        events: Optional[List[HeartbeatEventConfig]] = None,
    ) -> None:
        self._dispatch = dispatch_fn
        self._handlers: Dict[str, HeartbeatHandler] = {}
        for cfg in events if events is not None else DEFAULT_EVENTS:
            self._handlers[cfg.event_name] = self._build_handler(cfg)

    def _build_handler(self, cfg: HeartbeatEventConfig) -> HeartbeatHandler:
        if cfg.kind == "greeting_pool":
            return GreetingPoolHandler(pool=cfg.pool or [])
        return LLMHandler(dispatch_fn=self._dispatch, prompt=cfg.prompt or "")

    def register(self, event_name: str, handler: HeartbeatHandler) -> "HeartbeatManager":
        self._handlers[event_name] = handler
        return self

    def unregister(self, event_name: str) -> None:
        self._handlers.pop(event_name, None)

    @property
    def registered_events(self) -> List[str]:
        return list(self._handlers.keys())

    async def dispatch(
        self,
        event_name: str,
        data: dict,
        session_token: str,
        conversation_id: str,
        reply_fn: ReplyFn,
    ) -> None:
        handler = self._handlers.get(event_name)
        if handler is None:
            logger.debug("HeartbeatManager: no handler for event {!r}, ignoring", event_name)
            return

        try:
            await handler.handle(event_name, data, session_token, conversation_id, reply_fn)
        except Exception:
            logger.exception("HeartbeatManager: handler for {!r} raised an error", event_name)
