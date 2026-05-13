import sys
from typing import Any, Dict, List, Optional

from rich.table import Table

from waifu.cli._console import console, err_console
from waifu.cli._remote import ServerOffline, online_state
from waifu.cli._remote import request as remote_request
from waifu.skill.installer import (
    SkillInstallError,
)
from waifu.skill.installer import (
    install as install_skill,
)
from waifu.skill.installer import (
    uninstall as uninstall_skill,
)
from waifu.skill.loader import scan_skills
from waifu.store import AppPaths

_REGISTRY_TODO = "[yellow]TODO:[/yellow] requires skills registry integration (skills.sh)"


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
    console.print("  [cyan]skill install[/cyan] [green]<source>[/green]       Install (local path or user/repo[@ref])")
    console.print("  [cyan]skill uninstall[/cyan] [green]<name>[/green]       Remove an installed skill")
    console.print("  [cyan]skill reload[/cyan]                  Re-scan skills dir (online only)")
    console.print("  [cyan]skill search[/cyan] [green]<query>[/green]         (TODO) search skills.sh registry")
    console.print("  [cyan]skill update[/cyan]                  (TODO) update installed skills")
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
        err_console.print("[red]Usage:[/red] waifu skill install <path-or-user/repo[@ref]>")
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


def _cmd_search(args: List[str]) -> None:
    if not args:
        err_console.print("[red]Usage:[/red] waifu skill search <query>")
        sys.exit(1)
    err_console.print(_REGISTRY_TODO)


def _cmd_update(_args: List[str]) -> None:
    err_console.print(_REGISTRY_TODO)
