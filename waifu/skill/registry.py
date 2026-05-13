from typing import Dict, List, Optional, Tuple

from waifu.skill.manifest import SkillManifest


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: Dict[str, SkillManifest] = {}

    def add(self, manifest: SkillManifest) -> None:
        self._skills[manifest.name] = manifest

    def remove(self, name: str) -> None:
        self._skills.pop(name, None)

    def get(self, name: str) -> Optional[SkillManifest]:
        return self._skills.get(name)

    def list(self) -> List[SkillManifest]:
        return list(self._skills.values())

    def list_descriptions(self) -> List[Tuple[str, str]]:
        return [(s.name, s.description) for s in self._skills.values()]

    def clear(self) -> None:
        self._skills.clear()

    def __len__(self) -> int:
        return len(self._skills)
