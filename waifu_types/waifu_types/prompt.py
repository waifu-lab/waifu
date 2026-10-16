from typing import List

from pydantic import BaseModel, Field


class SystemPromptLayers(BaseModel):
    """
    分層的 system prompt 容器
    """

    behavior_rules: List[str] = Field(default_factory=list)
    identity: List[str] = Field(default_factory=list)
    tool_constraints: List[str] = Field(default_factory=list)
    output_discipline: List[str] = Field(default_factory=list)
    user_custom: List[str] = Field(default_factory=list)
    runtime: List[str] = Field(default_factory=list)

    def render(self) -> str:
        ordered: List[str] = [
            *self.behavior_rules,
            *self.identity,
            *self.tool_constraints,
            *self.output_discipline,
            *self.user_custom,
            *self.runtime,
        ]
        return "\n\n".join(s for s in ordered if s)
