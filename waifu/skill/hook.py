from typing import Optional

from waifu_types import BaseHook, HookContext

from waifu.skill.registry import SkillRegistry


class SkillPromptHook(BaseHook):
    name = "skill-prompt"
    priority = 50

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    def system_prompt_fragment(self, ctx: HookContext) -> Optional[str]:  # noqa: ARG002
        items = self._registry.list_descriptions()
        if not items:
            return None
        lines = [
            "## 可用的 Skills",
            '若以下某個 skill 的描述符合當前任務，呼叫 `skill(name="…")` 工具來載入完整指示。',
        ]
        for name, desc in items:
            lines.append(f"- **{name}**：{desc}")
        return "\n".join(lines)
