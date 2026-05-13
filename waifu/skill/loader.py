from pathlib import Path
from typing import List

from waifu.logger import logger
from waifu.skill.manifest import SkillManifest, SkillParseError, parse_skill_md


def scan_skills(skills_dir: Path) -> List[SkillManifest]:
    """Scan `skills_dir/*/SKILL.md`. Malformed skills are logged and skipped."""
    result: List[SkillManifest] = []
    if not skills_dir.exists():
        return result

    for child in skills_dir.iterdir():
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            result.append(parse_skill_md(skill_md))
        except SkillParseError as e:
            logger.warning("Skipping malformed skill at {}: {}", skill_md, e)
        except Exception:
            logger.exception("Failed to load skill at {}", skill_md)
    return result
