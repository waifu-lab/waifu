from typing import List

from pydantic import BaseModel, Field


class SystemPromptLayers(BaseModel):
    """分層的 system prompt 容器。
    """

    identity: List[str] = Field(default_factory=list)
    behavior_rules: List[str] = Field(default_factory=list)
    tool_constraints: List[str] = Field(default_factory=list)
    output_discipline: List[str] = Field(default_factory=list)
    user_custom: List[str] = Field(default_factory=list)

    def render(self) -> str:
        ordered: List[str] = [
            *self.identity,
            *self.behavior_rules,
            *self.tool_constraints,
            *self.output_discipline,
            *self.user_custom,
        ]
        return "\n\n".join(s for s in ordered if s)
