import io
import json
import shutil
import tarfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from waifu.logger import logger
from waifu.skill.manifest import SkillParseError, parse_skill_md


class SkillInstallError(RuntimeError):
    pass


def _write_installed_json(target: Path, source: str, ref: Optional[str] = None) -> None:
    meta = {
        "source": source,
        "ref": ref,
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }
    (target / "installed.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _find_skill_dir(root: Path) -> Path:
    """Locate the directory containing SKILL.md (root or single nested level)."""
    if (root / "SKILL.md").is_file():
        return root
    # GitHub tarballs unpack as <repo>-<sha>/...; search one level
    for child in root.iterdir():
        if child.is_dir() and (child / "SKILL.md").is_file():
            return child
    # Then search recursively (shallow) for any SKILL.md
    for skill_md in root.rglob("SKILL.md"):
        return skill_md.parent
    raise SkillInstallError(f"no SKILL.md found under {root}")


def _safe_target(skills_dir: Path, name: str) -> Path:
    skills_dir = skills_dir.resolve()
    target = (skills_dir / name).resolve()
    if skills_dir not in target.parents and target != skills_dir:
        raise SkillInstallError(f"refusing to install outside skills_dir: {target}")
    if target == skills_dir:
        raise SkillInstallError("invalid skill name")
    return target


def install_local(src: Path, skills_dir: Path, *, overwrite: bool = False) -> Path:
    src = src.expanduser().resolve()
    if not src.exists():
        raise SkillInstallError(f"source path not found: {src}")

    skill_root = _find_skill_dir(src) if src.is_dir() else src.parent
    manifest = parse_skill_md(skill_root / "SKILL.md")

    target = _safe_target(skills_dir, manifest.name)
    if target.exists():
        if not overwrite:
            raise SkillInstallError(f"skill '{manifest.name}' already installed at {target}")
        shutil.rmtree(target)

    shutil.copytree(skill_root, target)
    _write_installed_json(target, source=f"local:{src}")
    logger.info("Installed skill '{}' from {}", manifest.name, src)
    return target


def install_github(spec: str, skills_dir: Path, *, overwrite: bool = False) -> Path:
    """`user/repo`, `user/repo@ref`, or a full GitHub URL → tarball download."""
    user_repo, _, ref = spec.partition("@")
    ref = ref or "HEAD"
    if user_repo.startswith("http"):
        parts = user_repo.rstrip("/").split("/")
        if "github.com" not in parts:
            raise SkillInstallError(f"unsupported URL: {spec}")
        idx = parts.index("github.com")
        if len(parts) < idx + 3:
            raise SkillInstallError(f"invalid GitHub URL: {spec}")
        owner, repo = parts[idx + 1], parts[idx + 2]
        if len(parts) >= idx + 5 and parts[idx + 3] == "tree":
            ref = parts[idx + 4]
    else:
        if user_repo.count("/") != 1:
            raise SkillInstallError(f"expected 'user/repo' or URL, got: {spec}")
        owner, repo = user_repo.split("/")

    tarball_url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/{ref}"
    logger.info("Downloading {}", tarball_url)
    try:
        with urllib.request.urlopen(tarball_url, timeout=30) as resp:  # noqa: S310
            payload = resp.read()
    except Exception as e:
        raise SkillInstallError(f"download failed: {e}") from e

    extract_root = skills_dir / f".tmp-{owner}-{repo}-{ref}".replace("/", "_")
    if extract_root.exists():
        shutil.rmtree(extract_root)
    extract_root.mkdir(parents=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tf:
            tf.extractall(extract_root)  # noqa: S202

        skill_root = _find_skill_dir(extract_root)
        try:
            manifest = parse_skill_md(skill_root / "SKILL.md")
        except SkillParseError as e:
            raise SkillInstallError(str(e)) from e

        target = _safe_target(skills_dir, manifest.name)
        if target.exists():
            if not overwrite:
                raise SkillInstallError(f"skill '{manifest.name}' already installed at {target}")
            shutil.rmtree(target)
        shutil.copytree(skill_root, target)
        _write_installed_json(target, source=f"github:{owner}/{repo}", ref=ref)
        logger.info("Installed skill '{}' from github:{}/{}@{}", manifest.name, owner, repo, ref)
        return target
    finally:
        shutil.rmtree(extract_root, ignore_errors=True)


def uninstall(name: str, skills_dir: Path) -> None:
    target = _safe_target(skills_dir, name)
    if not target.exists():
        raise SkillInstallError(f"skill '{name}' is not installed")
    shutil.rmtree(target)
    logger.info("Uninstalled skill '{}'", name)


def install(source: str, skills_dir: Path, *, overwrite: bool = False) -> Path:
    """Dispatch by source spec."""
    if source.startswith(("http://", "https://")) or ("/" in source and not Path(source).exists()):
        return install_github(source, skills_dir, overwrite=overwrite)
    return install_local(Path(source), skills_dir, overwrite=overwrite)
