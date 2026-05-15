from waifu.skill.registry import SkillRegistry
from waifu_types import BaseHook, HookContext, SystemPromptLayers


class SkillPromptHook(BaseHook):
    name = "skill-prompt"
    priority = 50

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    def contribute_prompt(self, ctx: HookContext, layers: SystemPromptLayers) -> None:  # noqa: ARG002
        items = self._registry.list_descriptions()
        if not items:
            return
        lines = [
            "## 可用的 Skills",
            '若以下某個 skill 的描述符合當前任務，呼叫 `skill(name="…")` 工具來載入完整指示。',
        ]
        for name, desc in items:
            lines.append(f"- **{name}**：{desc}")
        layers.tool_constraints.append("\n".join(lines))
