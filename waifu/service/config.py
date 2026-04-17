from typing import Any

from waifu.agent.context import ContextBuilder
from waifu.agent.runner import AgentRunner
from waifu.store.repositories.config import AppConfigRepository


class AppConfigService:
    _HOT_KEYS = {
        "provider.model",
        "provider.temperature",
        "provider.max_tokens",
        "context.system_prompt_template",
        "context.max_history_messages",
        "context.history_strategy",
    }

    def __init__(self, repo: AppConfigRepository, context_builder: ContextBuilder, agent_runner: AgentRunner) -> None:
        self._repo = repo
        self._cb = context_builder
        self._ar = agent_runner

    def get_all(self) -> dict:
        return self._repo.get_all()

    def get(self, key: str, default: Any = None) -> Any:
        return self._repo.get(key, default)

    def set(self, key: str, value: Any) -> dict:
        self._repo.set(key, value)
        result: dict = {"key": key, "status": "saved"}
        if key in self._HOT_KEYS:
            self._apply_hot(key, value)
        elif key.startswith("gateway."):
            result["note"] = "requires restart"
        return result

    def _apply_hot(self, key: str, value: Any) -> None:
        section, field = key.split(".", 1)
        if section == "context":
            setattr(self._cb.config, field, value)
        elif section == "provider":
            setattr(self._ar.provider, field, value)
