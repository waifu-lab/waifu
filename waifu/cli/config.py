import json
import sys
from typing import Any, Dict, List

from waifu.cli._console import console, err_console
from waifu.store.paths import AppPaths


def _paths() -> AppPaths:
    return AppPaths.resolve()


def _load_raw() -> Dict[str, Any]:
    p = _paths().config_file
    if not p.exists():
        return {}
    import tomllib

    with open(p, "rb") as f:
        return tomllib.load(f)


def _save_raw(data: Dict[str, Any]) -> None:
    import tomli_w

    p = _paths().config_file
    with open(p, "wb") as f:
        tomli_w.dump(data, f)


def _get_nested(data: Dict[str, Any], path: str) -> Any:
    cur = data
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def _set_nested(data: Dict[str, Any], path: str, value: Any) -> None:
    keys = path.split(".")
    cur = data
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = value


def _parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw


def cmd_config(args: List[str]) -> None:
    if not args or args[0] in ("-h", "--help"):
        _help()
        return

    sub = args[0]
    rest = args[1:]

    if sub == "list":
        _cmd_list()
    elif sub == "get":
        if not rest:
            err_console.print("[red]Usage:[/red] waifu config get <path>")
            sys.exit(1)
        _cmd_get(rest[0])
    elif sub == "set":
        if len(rest) < 2:
            err_console.print("[red]Usage:[/red] waifu config set <path> <value>")
            sys.exit(1)
        _cmd_set(rest[0], rest[1])
    else:
        err_console.print(f"[red]Unknown config subcommand:[/red] {sub}")
        _help()
        sys.exit(1)


def _help() -> None:
    console.print()
    console.print("[bold]waifu config[/bold] — manage settings")
    console.print()
    console.print("  [cyan]config list[/cyan]                List all settings (TOML)")
    console.print(
        "  [cyan]config get[/cyan] [green]<path>[/green]          Read a setting (e.g. [dim]provider.model[/dim])"
    )
    console.print("  [cyan]config set[/cyan] [green]<path> <value>[/green]  Update a setting")
    console.print()
    console.print(f"  Config file: [dim]{_paths().config_file}[/dim]")
    console.print()


def _cmd_list() -> None:
    p = _paths().config_file
    if not p.exists():
        console.print("[yellow]No config found.[/yellow] Run [bold]waifu init[/bold] to get started.")
        console.print(f"[dim]Expected: {p}[/dim]")
        return
    from rich.syntax import Syntax

    console.print(Syntax(p.read_text(encoding="utf-8"), "toml", theme="ansi_dark"))


def _cmd_get(path: str) -> None:
    data = _load_raw()
    value = _get_nested(data, path)
    if value is None:
        err_console.print(f"[yellow]Not set:[/yellow] {path}")
        sys.exit(1)
    console.print(json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value)


def _cmd_set(path: str, raw_value: str) -> None:
    data = _load_raw()
    value = _parse_value(raw_value)
    _set_nested(data, path, value)
    _save_raw(data)
    console.print(f"[green][OK][/green] [bold]{path}[/bold] = {json.dumps(value, ensure_ascii=False)}")
