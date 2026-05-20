from pathlib import Path
from typing import List

from waifu.logger import logger
from waifu.skill.manifest import SkillManifest, SkillParseError, parse_skill_md


def _scan_one_dir(base: Path, result: List[SkillManifest]) -> None:
    for child in base.iterdir():
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


SKILLSSH_GLOBAL_DIR = Path.home() / ".agents" / "skills"


def scan_skills(skills_dir: Path) -> List[SkillManifest]:
    """Scan skills_dir for SKILL.md files, plus the shared ~/.agents/skills dir.

    Layouts checked:
    - skills_dir/<name>/SKILL.md       (waifu-native installs)
    - ~/.agents/skills/<name>/SKILL.md (npx skills add -g, shared with Claude Code etc.)
    """
    result: List[SkillManifest] = []

    if skills_dir.exists():
        _scan_one_dir(skills_dir, result)

    already = {m.name for m in result}
    if SKILLSSH_GLOBAL_DIR.is_dir():
        for child in SKILLSSH_GLOBAL_DIR.iterdir():
            if not child.is_dir() or child.name in already:
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
