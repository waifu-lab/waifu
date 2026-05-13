from hai.tool import Tool

from waifu.skill.registry import SkillRegistry


def make_skill_tool(registry: SkillRegistry) -> Tool:
    """Build the progressive-disclosure `skill` tool bound to a registry."""

    def _invoke(name: str) -> str:
        manifest = registry.get(name)
        if manifest is None:
            available = ", ".join(s.name for s in registry.list()) or "(none)"
            return f"[error] skill '{name}' not found. available: {available}"
        return manifest.body

    return Tool(
        name="skill",
        description=(
            "Load the full body of an available skill by name. "
            "Use this when one of the listed skills matches the current task — "
            "the body contains step-by-step instructions you should then follow."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The skill's name, as shown in the available skills list.",
                },
            },
            "required": ["name"],
        },
        func=_invoke,
    )
