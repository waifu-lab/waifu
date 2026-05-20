import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.table import Table

from waifu.cli._console import console, err_console
from waifu.cli._remote import ServerOffline, online_state
from waifu.cli._remote import request as remote_request
from waifu.skill.installer import SkillInstallError, install_github
from waifu.skill.installer import install as install_skill
from waifu.skill.installer import uninstall as uninstall_skill
from waifu.skill.loader import scan_skills
from waifu.store import AppPaths


def cmd_skill(args: List[str]) -> None:
    if not args or args[0] in ("-h", "--help"):
        _help()
        return

    sub = args[0]
    rest = args[1:]

    dispatch = {
        "list": _cmd_list,
        "search": _cmd_search,
        "find": _cmd_search,
        "install": _cmd_install,
        "update": _cmd_update,
        "uninstall": _cmd_uninstall,
        "reload": _cmd_reload,
    }

    if sub not in dispatch:
        err_console.print(f"[red]Unknown subcommand:[/red] {sub}")
        _help()
        sys.exit(1)

    dispatch[sub](rest)


def _help() -> None:
    console.print()
    console.print("[bold]waifu skill[/bold] — manage skills")
    console.print()
    console.print("  [cyan]skill list[/cyan]                    List installed skills")
    console.print("  [cyan]skill install[/cyan] [green]<src>[/green]          name/skills.sh  user/repo/GitHub  path")
    console.print("  [cyan]skill uninstall[/cyan] [green]<name>[/green]       Remove an installed skill")
    console.print("  [cyan]skill reload[/cyan]                  Re-scan skills dir (online only)")
    console.print("  [cyan]skill search[/cyan] [green]<query>[/green]         Search skills.sh (npx skills search)")
    console.print("  [cyan]skill update[/cyan] [green][name][/green]           Re-download installed skill(s)")
    console.print()
    console.print("[dim]If a waifu server is running locally, changes hot-reload into its SkillRegistry.[/dim]")
    console.print("[dim]Otherwise files are written to disk and apply on next `waifu start`.[/dim]")
    console.print()


def _mode_tag() -> str:
    return "[bold magenta]online[/bold magenta]" if online_state() else "[bold yellow]offline[/bold yellow]"


def _try_online(method: str, path: str, *, json_body: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    try:
        resp = remote_request(method, path, json=json_body)
    except ServerOffline:
        return None
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        err_console.print(f"[red]Server error ({resp.status_code}):[/red] {detail}")
        sys.exit(1)
    try:
        return resp.json()
    except Exception:
        return {}


def _try_online_list() -> Optional[List[Dict[str, Any]]]:
    try:
        resp = remote_request("GET", "/skill/")
    except ServerOffline:
        return None
    if resp.status_code != 200:
        return None
    return resp.json()


def _cmd_list(_args: List[str]) -> None:
    rows = _try_online_list()
    if rows is None:
        rows = [
            {"name": s.name, "description": s.description, "allowed_tools": s.allowed_tools}
            for s in scan_skills(AppPaths.resolve().skills_dir)
        ]

    mode = _mode_tag()
    if not rows:
        paths = AppPaths.resolve()
        console.print(f"[dim]No skills installed at[/dim] {paths.skills_dir}  [{mode}]")
        return

    table = Table(title=f"Installed Skills  [{mode}]", show_lines=False)
    table.add_column("Name", style="bold cyan")
    table.add_column("Description")
    table.add_column("Allowed tools", style="dim")
    for row in rows:
        tools = row.get("allowed_tools") or []
        table.add_row(row["name"], row.get("description", ""), ", ".join(tools) or "—")
    console.print(table)


def _cmd_install(args: List[str]) -> None:
    if not args:
        err_console.print("[red]Usage:[/red] waifu skill install <name|user/repo[@ref]|path>")
        sys.exit(1)
    overwrite = "--force" in args or "-f" in args
    source = next((a for a in args if not a.startswith("-")), None)
    if source is None:
        err_console.print("[red]Missing source argument[/red]")
        sys.exit(1)

    result = _try_online("POST", "/skill/install", json_body={"source": source, "overwrite": overwrite})
    if result is not None:
        console.print(f"[green]Installed[/green] [bold]{result.get('name', '?')}[/bold]  [{_mode_tag()}]")
        console.print(f"[dim]→ {result.get('path', '')}[/dim]")
        return

    paths = AppPaths.resolve()

    if _is_skillssh_spec(source):
        _install_skillssh(source, paths.skills_dir, overwrite=overwrite)
        console.print("[dim]Server not running — skill picks up on next `waifu start`.[/dim]")
        return

    try:
        target = install_skill(source, paths.skills_dir, overwrite=overwrite)
    except SkillInstallError as e:
        err_console.print(f"[red]Install failed:[/red] {e}")
        sys.exit(1)
    console.print(f"[green]Installed[/green] → {target}  [{_mode_tag()}]")
    console.print("[dim]Server not running — skill picks up on next `waifu start`.[/dim]")


def _cmd_uninstall(args: List[str]) -> None:
    if not args:
        err_console.print("[red]Usage:[/red] waifu skill uninstall <name>")
        sys.exit(1)
    name = args[0]

    result = _try_online("DELETE", f"/skill/{name}")
    if result is not None:
        console.print(f"[green]Uninstalled[/green] [bold]{name}[/bold]  [{_mode_tag()}]")
        return

    paths = AppPaths.resolve()
    try:
        uninstall_skill(name, paths.skills_dir)
    except SkillInstallError as e:
        err_console.print(f"[red]Uninstall failed:[/red] {e}")
        sys.exit(1)
    console.print(f"[green]Uninstalled[/green] [bold]{name}[/bold]  [{_mode_tag()}]")


def _cmd_reload(_args: List[str]) -> None:
    result = _try_online("POST", "/skill/reload")
    if result is None:
        err_console.print("[yellow]Server not running — nothing to reload.[/yellow]")
        err_console.print("[dim]Skills are scanned automatically on `waifu start`.[/dim]")
        sys.exit(0)
    console.print(f"[green]Reloaded[/green] {result.get('count', '?')} skill(s)  [{_mode_tag()}]")


def _run_npx_skills(subcmd: str, *args: str, cwd: Optional[Path] = None) -> int:
    """Run `npx --yes skills <subcmd> [args]`. Streams to terminal. Returns exit code."""
    cmd = ["npx", "--yes", "skills", subcmd, *args]
    shell = sys.platform == "win32"
    try:
        return subprocess.run(cmd, cwd=cwd, shell=shell).returncode  # noqa: S603, S604
    except FileNotFoundError:
        err_console.print("[red]npx not found[/red] — install Node.js to use the skills.sh registry.")
        return 127


def _is_skillssh_spec(source: str) -> bool:
    """True if source is a skills.sh spec: owner/repo@skill or bare@skill."""
    return (
        "@" in source
        and not source.startswith(("http://", "https://"))
        and not source.startswith((".", "~"))
        and not Path(source).is_absolute()
    )


def _skillssh_skill_name(spec: str) -> str:
    """Extract the skill name part: owner/repo@skill-name -> skill-name."""
    return spec.rpartition("@")[2] or spec


def _write_installed_json(target: Path, source: str) -> None:
    meta = {"source": source, "ref": None, "installed_at": datetime.now(timezone.utc).isoformat()}
    (target / "installed.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _skillssh_target(skill_name: str) -> Path:
    """Global path where `npx skills add -g` places the skill."""
    from waifu.skill.loader import SKILLSSH_GLOBAL_DIR

    return SKILLSSH_GLOBAL_DIR / skill_name


def _install_skillssh(spec: str, skills_dir: Path, *, overwrite: bool = False) -> None:
    skill_name = _skillssh_skill_name(spec)
    target = _skillssh_target(skill_name)
    if target.exists():
        if not overwrite:
            err_console.print(f"[red]Skill '{skill_name}' already installed.[/red] Use --force to overwrite.")
            sys.exit(1)
        shutil.rmtree(target)
    skills_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"Installing [bold cyan]{spec}[/bold cyan] from skills.sh...")
    rc = _run_npx_skills("add", "-g", spec)
    if rc != 0:
        err_console.print(f"[red]npx skills add failed[/red] (exit {rc})")
        sys.exit(rc)
    if target.is_dir():
        _write_installed_json(target, source=f"skillssh:{spec}")
        console.print(f"[green]Installed[/green] [bold]{skill_name}[/bold] -> {target}")
    else:
        console.print("[green]Done[/green]  [dim](installed by npx skills)[/dim]")


def _read_installed_meta(skills_dir: Path) -> List[Dict[str, Any]]:
    result = []
    if not skills_dir.exists():
        return result
    for child in skills_dir.iterdir():
        if not child.is_dir():
            continue
        meta_file = child / "installed.json"
        if not meta_file.is_file():
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            result.append({"name": child.name, **meta})
        except Exception:
            pass
    return result


def _cmd_search(args: List[str]) -> None:
    query_parts = [a for a in args if not a.startswith("-")]
    query = " ".join(query_parts)
    if not query:
        err_console.print("[red]Usage:[/red] waifu skill search <query>")
        sys.exit(1)
    rc = _run_npx_skills("find", query)
    if rc != 0:
        sys.exit(rc)


def _update_one(meta: Dict[str, Any], skills_dir: Path) -> bool:
    name: str = meta["name"]
    source: str = meta.get("source", "")
    ref: str = meta.get("ref") or "HEAD"

    if source.startswith("skillssh:"):
        spec = source[len("skillssh:") :]
        skill_name = _skillssh_skill_name(spec)
        console.print(f"Updating [bold cyan]{name}[/bold cyan] <- skills.sh...")
        rc = _run_npx_skills("update", "-g", skill_name, "--yes")
        if rc != 0:
            err_console.print(f"  [red]failed[/red] npx skills update (exit {rc})")
            return False
        console.print(f"  [green]ok[/green] {_skillssh_target(skill_name)}")
        return True

    if source.startswith("github:"):
        spec = source[len("github:") :]
        if ref and ref != "HEAD":
            spec = f"{spec}@{ref}"
        console.print(f"Updating [bold cyan]{name}[/bold cyan] ← [dim]{spec}[/dim]…")
        try:
            target = install_github(spec, skills_dir, overwrite=True)
            console.print(f"  [green]✓[/green] {target}")
            return True
        except SkillInstallError as e:
            err_console.print(f"  [red]✗[/red] {e}")
            return False

    console.print(f"[dim]Skipping[/dim] [bold]{name}[/bold]  [dim](local source)[/dim]")
    return False


def _update_metas(metas: List[Dict[str, Any]], skills_dir: Path) -> tuple[int, int]:
    results = [_update_one(m, skills_dir) for m in metas]
    return sum(results), len(results) - sum(results)


def _parse_update_args(args: List[str]) -> Optional[str]:
    i = 0
    while i < len(args):
        if args[i] in ("--name", "-n") and i + 1 < len(args):
            return args[i + 1]
        if not args[i].startswith("-"):
            return args[i]
        i += 1
    return None


def _cmd_update(args: List[str]) -> None:
    target_name = _parse_update_args(args)

    paths = AppPaths.resolve()
    metas = _read_installed_meta(paths.skills_dir)

    if target_name:
        metas = [m for m in metas if m["name"] == target_name]
        if not metas:
            err_console.print(f"[red]Skill '{target_name}' not found or has no install metadata.[/red]")
            sys.exit(1)

    if not metas:
        console.print("[dim]No updatable skills found (no installed.json metadata).[/dim]")
        return

    updated, failed = _update_metas(metas, paths.skills_dir)

    summary = f"Updated [green]{updated}[/green] skill(s)"
    if failed:
        summary += f", [red]{failed}[/red] failed"
    console.print(summary + f"  [{_mode_tag()}]")

    if updated and online_state():
        _try_online("POST", "/skill/reload")
        console.print("[dim]Reloaded skill registry on running server.[/dim]")
    elif updated:
        console.print("[dim]Server not running — skills apply on next `waifu start`.[/dim]")
