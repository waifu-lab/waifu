import json
import sys
from typing import Any, Dict, List
from urllib.parse import quote

from rich.table import Table

from waifu.cli._console import console, err_console
from waifu.cli._remote import ServerOffline, online_state
from waifu.cli._remote import request as remote_request
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
        _cmd_set(rest[0], " ".join(rest[1:]))
    else:
        err_console.print(f"[red]Unknown config subcommand:[/red] {sub}")
        _help()
        sys.exit(1)


def _help() -> None:
    console.print()
    console.print("[bold]waifu config[/bold] — manage waifu settings")
    console.print()
    console.print("  [cyan]config list[/cyan]                List settings")
    console.print(
        "  [cyan]config get[/cyan] [green]<path>[/green]          Read a setting (e.g. [dim]provider.model[/dim])"
    )
    console.print("  [cyan]config set[/cyan] [green]<path> <value>[/green]  Update a setting")
    console.print()
    console.print(
        '  Values are parsed as JSON when possible: '
        '[dim]true[/dim], [dim]123[/dim], [dim]0.7[/dim], [dim]["a"][/dim]'
    )
    console.print(f"  Config file: [dim]{_paths().config_file}[/dim]")
    console.print("  If the local server is running, this updates waifu runtime config via API.")
    console.print("  Otherwise it updates config.toml for the next [bold]waifu start[/bold].")
    console.print()


def _mode_tag() -> str:
    state = online_state()
    if state is True:
        return "[bold magenta]online[/bold magenta]"
    if state is False:
        return "[bold yellow]offline[/bold yellow]"
    return "[dim]unknown[/dim]"


def _server_error(resp) -> None:
    try:
        detail = resp.json().get("detail", resp.text)
    except Exception:
        detail = resp.text
    err_console.print(f"[red]Server error ({resp.status_code}):[/red] {detail}")
    sys.exit(1)


def _format_value(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _cmd_list() -> None:
    try:
        resp = remote_request("GET", "/config/")
    except ServerOffline:
        _cmd_list_file()
        return

    if resp.status_code >= 400:
        _server_error(resp)

    rows = resp.json()
    _print_runtime_config(rows)


def _cmd_list_file() -> None:
    p = _paths().config_file
    if not p.exists():
        console.print("[yellow]No config found.[/yellow] Run [bold]waifu init[/bold] to get started.")
        console.print(f"[dim]Expected: {p}[/dim]")
        return
    from rich.syntax import Syntax

    console.print(Syntax(p.read_text(encoding="utf-8"), "toml", theme="ansi_dark"))
    console.print(f"[dim]Source: {p}  [{_mode_tag()}][/dim]")


def _print_runtime_config(rows: Dict[str, Any]) -> None:
    if not rows:
        console.print(f"[dim]No runtime config values set.  [{_mode_tag()}][/dim]")
        return

    table = Table(title=f"Waifu Config  [{_mode_tag()}]", show_lines=False)
    table.add_column("Key", style="bold cyan", no_wrap=True)
    table.add_column("Value")
    for key in sorted(rows):
        table.add_row(key, _format_value(rows[key]))
    console.print(table)


def _cmd_get(path: str) -> None:
    try:
        resp = remote_request("GET", f"/config/{quote(path, safe='')}")
    except ServerOffline:
        _cmd_get_file(path)
        return

    if resp.status_code == 404:
        err_console.print(f"[yellow]Not set:[/yellow] {path}")
        sys.exit(1)
    if resp.status_code >= 400:
        _server_error(resp)

    body = resp.json()
    console.print(_format_value(body.get("value")))


def _cmd_get_file(path: str) -> None:
    data = _load_raw()
    value = _get_nested(data, path)
    if value is None:
        err_console.print(f"[yellow]Not set:[/yellow] {path}")
        sys.exit(1)
    console.print(_format_value(value))


def _cmd_set(path: str, raw_value: str) -> None:
    value = _parse_value(raw_value)
    try:
        resp = remote_request("PUT", f"/config/{quote(path, safe='')}", json={"value": value})
    except ServerOffline:
        _cmd_set_file(path, value)
        return

    if resp.status_code >= 400:
        _server_error(resp)

    result = resp.json()
    console.print(f"[green][OK][/green] [bold]{path}[/bold] = {_format_value(value)}  [{_mode_tag()}]")
    if note := result.get("note"):
        console.print(f"[yellow]Note:[/yellow] {note}")


def _cmd_set_file(path: str, value: Any) -> None:
    if value is None:
        err_console.print("[red]Cannot write null to TOML config file.[/red]")
        sys.exit(1)
    data = _load_raw()
    _set_nested(data, path, value)
    _save_raw(data)
    console.print(f"[green][OK][/green] [bold]{path}[/bold] = {_format_value(value)}  [{_mode_tag()}]")
