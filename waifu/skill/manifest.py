from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class SkillManifest:
    name: str
    description: str
    body: str
    path: Path
    allowed_tools: List[str] = field(default_factory=list)


class SkillParseError(ValueError):
    pass


def _split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        raise SkillParseError("missing frontmatter delimiter '---' at start")
    rest = text[3:].lstrip("\r\n")
    end = rest.find("\n---")
    if end == -1:
        raise SkillParseError("missing closing frontmatter delimiter '---'")
    fm = rest[:end]
    body_start = end + len("\n---")
    body = rest[body_start:].lstrip("\r\n")
    return fm, body


def _parse_inline_list(value: str) -> List[str]:
    inner = value.strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]
    return [item.strip().strip("\"'") for item in inner.split(",") if item.strip()]


def _parse_frontmatter(fm: str) -> dict:
    """Minimal YAML subset: `key: value` and `key: [a, b]` plus dash-list blocks.

    Enough for the SKILL.md schema we expect.
    """
    data: dict = {}
    current_key: Optional[str] = None
    current_list: Optional[List[str]] = None
    for raw_line in fm.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        stripped = line.lstrip()
        if stripped.startswith("- ") and current_key is not None and current_list is not None:
            current_list.append(stripped[2:].strip().strip("\"'"))
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        current_key = key
        current_list = None
        if not value:
            current_list = []
            data[key] = current_list
        elif value.startswith("["):
            data[key] = _parse_inline_list(value)
        else:
            data[key] = value.strip("\"'")
    return data


def parse_skill_md(path: Path) -> SkillManifest:
    text = path.read_text(encoding="utf-8")
    fm_text, body = _split_frontmatter(text)
    data = _parse_frontmatter(fm_text)

    name = data.get("name")
    description = data.get("description")
    if not isinstance(name, str) or not name:
        raise SkillParseError(f"{path}: frontmatter missing 'name'")
    if not isinstance(description, str) or not description:
        raise SkillParseError(f"{path}: frontmatter missing 'description'")

    allowed = data.get("allowed-tools") or data.get("allowed_tools") or []
    if isinstance(allowed, str):
        allowed = _parse_inline_list(allowed)
    if not isinstance(allowed, list):
        allowed = []

    return SkillManifest(
        name=name,
        description=description,
        body=body,
        path=path,
        allowed_tools=[str(t) for t in allowed],
    )
