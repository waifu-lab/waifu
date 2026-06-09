import pytest

from waifu.skill.manifest import SkillParseError, parse_skill_md
from waifu.skill.registry import SkillRegistry
from waifu.skill.tool import make_skill_tool


from pathlib import Path


def _write_skill(directory: Path, name: str, description: str, body: str, allowed_tools=None) -> Path:
    allowed = allowed_tools or []
    allowed_str = ", ".join(f'"{t}"' for t in allowed)
    content = f"""\
---
name: {name}
description: {description}
allowed-tools: [{allowed_str}]
---
{body}
"""
    p = directory / f"{name}.md"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.mark.unit
def test_parse_skill_md_basic(tmp_dir):
    p = _write_skill(tmp_dir, "greet", "Greet the user", "Say hello.", ["read", "shell"])
    m = parse_skill_md(p)
    assert m.name == "greet"
    assert "Greet" in m.description
    assert "Say hello." in m.body
    assert m.allowed_tools == ["read", "shell"]


@pytest.mark.unit
def test_parse_skill_md_no_allowed_tools(tmp_dir):
    p = _write_skill(tmp_dir, "plain", "A plain skill", "Do something.")
    m = parse_skill_md(p)
    assert m.allowed_tools == []


@pytest.mark.unit
def test_parse_skill_md_missing_name(tmp_dir):
    p = tmp_dir / "bad.md"
    p.write_text("---\ndescription: oops\n---\nbody\n", encoding="utf-8")
    with pytest.raises(SkillParseError, match="name"):
        parse_skill_md(p)


@pytest.mark.unit
def test_parse_skill_md_missing_frontmatter(tmp_dir):
    p = tmp_dir / "bad2.md"
    p.write_text("just body\n", encoding="utf-8")
    with pytest.raises(SkillParseError):
        parse_skill_md(p)


@pytest.mark.unit
def test_registry_add_get_list(tmp_dir):
    p = _write_skill(tmp_dir, "s1", "Skill one", "Do one.")
    m = parse_skill_md(p)
    reg = SkillRegistry()
    reg.add(m)
    assert reg.get("s1") is m
    assert len(reg.list()) == 1


@pytest.mark.unit
def test_registry_get_missing():
    reg = SkillRegistry()
    assert reg.get("nope") is None


@pytest.mark.unit
def test_registry_dedup_by_name(tmp_dir):
    p1 = _write_skill(tmp_dir, "dup", "First", "Body 1.")
    sub = tmp_dir / "sub"
    sub.mkdir()
    p2 = _write_skill(sub, "dup", "Second", "Body 2.")
    m1 = parse_skill_md(p1)
    m2 = parse_skill_md(p2)
    reg = SkillRegistry()
    reg.add(m1)
    reg.add(m2)
    assert len(reg.list()) == 1
    found = reg.get("dup")
    assert found is not None
    assert found.description == "Second"


@pytest.mark.unit
def test_skill_tool_returns_body(tmp_dir):
    p = _write_skill(tmp_dir, "hello", "Hello skill", "Print hello.")
    reg = SkillRegistry()
    reg.add(parse_skill_md(p))
    tool = make_skill_tool(reg)
    result = tool.func(name="hello")
    assert "Print hello." in result


@pytest.mark.unit
def test_skill_tool_unknown_returns_error():
    reg = SkillRegistry()
    tool = make_skill_tool(reg)
    result = tool.func(name="unknown_skill")
    assert "not found" in result
    assert "available" in result


@pytest.mark.unit
def test_skill_tool_lists_available(tmp_dir):
    p = _write_skill(tmp_dir, "visible", "A visible skill", "body.")
    reg = SkillRegistry()
    reg.add(parse_skill_md(p))
    tool = make_skill_tool(reg)
    result = tool.func(name="missing")
    assert "visible" in result


@pytest.mark.offline
def test_skill_registry_in_waifu(waifu, tmp_dir):
    """Skills added to waifu.skill_registry appear in the registry."""
    p = _write_skill(tmp_dir, "offline_skill", "Offline test skill", "Do nothing online.")
    from waifu.skill.manifest import parse_skill_md

    m = parse_skill_md(p)
    waifu.skill_registry.add(m)
    assert waifu.skill_registry.get("offline_skill") is not None


@pytest.mark.offline
def test_skill_tool_registered_in_plugin_registry(waifu):
    """'skill' tool must be present in the plugin registry (registered at __init__)."""
    tools = waifu.plugin_registry.get_all_tools()
    names = [t.name for t in tools]
    assert "skill" in names, f"'skill' not in {names}"


@pytest.mark.online
async def test_agent_loads_and_follows_skill(waifu, tmp_dir):
    """Agent calls the skill tool, reads the body, and follows the instruction."""
    from conftest import make_request

    marker = "SKILL_BODY_CONFIRMED_789"
    p = _write_skill(
        tmp_dir,
        "marker_skill",
        "Embeds a unique marker in the response",
        f'You MUST include the exact phrase "{marker}" verbatim in your reply.',
    )
    waifu.skill_registry.add(parse_skill_md(p))

    req = make_request("Call the skill tool with name='marker_skill' and follow the instructions in its body exactly.")
    response = await waifu._dispatch(req)
    assert marker in response.content, f"marker not found in: {response.content!r}"
