from pathlib import Path
from typing import Any, Dict, List

from waifu.skill.installer import install as install_source
from waifu.skill.installer import uninstall as uninstall_dir
from waifu.skill.loader import scan_skills
from waifu.skill.manifest import parse_skill_md
from waifu.skill.registry import SkillRegistry


class SkillService:
    def __init__(self, registry: SkillRegistry, skills_dir: Path) -> None:
        self._registry = registry
        self._skills_dir = skills_dir

    def list(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": s.name,
                "description": s.description,
                "allowed_tools": s.allowed_tools,
                "path": str(s.path),
            }
            for s in self._registry.list()
        ]

    def install(self, source: str, *, overwrite: bool = False) -> Dict[str, Any]:
        target = install_source(source, self._skills_dir, overwrite=overwrite)
        manifest = parse_skill_md(target / "SKILL.md")
        self._registry.add(manifest)
        return {
            "name": manifest.name,
            "description": manifest.description,
            "path": str(target),
        }

    def uninstall(self, name: str) -> None:
        uninstall_dir(name, self._skills_dir)
        self._registry.remove(name)

    def reload(self) -> int:
        self._registry.clear()
        manifests = scan_skills(self._skills_dir)
        for m in manifests:
            self._registry.add(m)
        return len(manifests)
