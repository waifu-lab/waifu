import json
import shlex
import sys
from typing import Any, Dict, List, Optional

from rich.table import Table

from waifu.cli._console import console, err_console
from waifu.cli._remote import ServerOffline, online_state
from waifu.cli._remote import request as remote_request

_REGISTRY_TODO = "[yellow]TODO:[/yellow] requires MCP registry integration"


def cmd_mcp(args: List[str]) -> None:
    if not args or args[0] in ("-h", "--help"):
        _help()
        return

    sub = args[0]
    rest = args[1:]

    dispatch = {
        "list": _cmd_list,
        "install": _cmd_install,
        "uninstall": _cmd_uninstall,
        "enable": _cmd_enable,
        "disable": _cmd_disable,
        "search": _cmd_search,
        "find": _cmd_search,
    }

    if sub not in dispatch:
        err_console.print(f"[red]Unknown subcommand:[/red] {sub}")
        _help()
        sys.exit(1)

    dispatch[sub](rest)


def _help() -> None:
    console.print()
    console.print("[bold]waifu mcp[/bold] — manage MCP servers")
    console.print()
    console.print("  [cyan]mcp list[/cyan]                              List configured MCP servers")
    console.print('  [cyan]mcp install[/cyan] [green]<name> --stdio "<cmd>"[/green] [dim][--env K=V][/dim]')
    console.print("  [cyan]mcp install[/cyan] [green]<name> --sse <url>[/green] [dim][--header K=V][/dim]")
    console.print("  [cyan]mcp uninstall[/cyan] [green]<name>[/green]                Remove an MCP server")
    console.print("  [cyan]mcp enable[/cyan] [green]<name>[/green]                   Enable a disabled server")
    console.print("  [cyan]mcp disable[/cyan] [green]<name>[/green]                  Disable a running server")
    console.print("  [cyan]mcp search[/cyan] [green]<query>[/green]                  (TODO) search MCP registry")
    console.print()
    console.print("[dim]If a waifu server is running locally, changes take effect immediately (hot-reload).[/dim]")
    console.print("[dim]Otherwise they are written to mcp.json and apply on next `waifu start`.[/dim]")
    console.print()


def _load_mcp_json() -> Dict[str, Any]:
    from waifu.store import AppPaths

    path = AppPaths.resolve().mcp_config_file
    if not path.is_file():
        return {"servers": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_mcp_json(data: Dict[str, Any]) -> None:
    from waifu.store import AppPaths

    path = AppPaths.resolve().mcp_config_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _mode_tag() -> str:
    return "[bold magenta]online[/bold magenta]" if online_state() else "[bold yellow]offline[/bold yellow]"


def _list_online() -> Optional[List[Dict[str, Any]]]:
    try:
        resp = remote_request("GET", "/mcp/")
    except ServerOffline:
        return None
    if resp.status_code != 200:
        return None
    return resp.json()


def _entry_type(entry: Dict[str, Any]) -> str:
    explicit = entry.get("type", "")
    if explicit in ("http", "sse") or "url" in entry:
        return "sse"
    return "stdio"


def _resolve_command(entry: Dict[str, Any]) -> List[str]:
    cmd = entry.get("command")
    if isinstance(cmd, str):
        return [cmd] + list(entry.get("args", []))
    return list(cmd) if cmd else []


def _list_offline() -> List[Dict[str, Any]]:
    data = _load_mcp_json()
    rows: List[Dict[str, Any]] = []
    for name, entry in data.get("servers", {}).items():
        type_ = _entry_type(entry)
        if type_ == "sse":
            target: Any = entry.get("url", "")
        else:
            target = _resolve_command(entry)
        rows.append(
            {
                "name": name,
                "type": type_,
                "enabled": entry.get("enabled", True),
                "target": target,
            }
        )
    return rows


def _format_target(target_field: Any) -> str:
    if target_field is None:
        return ""
    if isinstance(target_field, list):
        return " ".join(target_field)
    return str(target_field)


def _cmd_list(_args: List[str]) -> None:
    rows = _list_online()
    if rows is None:
        rows = _list_offline()

    mode = _mode_tag()
    if not rows:
        console.print(f"[dim]No MCP servers installed.[/dim]  [{mode}]")
        return

    table = Table(title=f"MCP Servers  [{mode}]", show_lines=False)
    table.add_column("Name", style="bold cyan")
    table.add_column("Type")
    table.add_column("Enabled")
    table.add_column("Command / URL")

    for row in rows:
        enabled = "[green]yes[/green]" if row.get("enabled", True) else "[dim]no[/dim]"
        table.add_row(row["name"], row["type"], enabled, _format_target(row.get("target")))

    console.print(table)


def _parse_kv_flags(rest: List[str], flag: str) -> tuple[Dict[str, str], List[str]]:
    result: Dict[str, str] = {}
    remaining: List[str] = []
    i = 0
    while i < len(rest):
        if rest[i] == f"--{flag}" and i + 1 < len(rest):
            kv = rest[i + 1]
            if "=" not in kv:
                raise ValueError(f"--{flag} expects key=value, got: {kv!r}")
            k, v = kv.split("=", 1)
            result[k] = v
            i += 2
        else:
            remaining.append(rest[i])
            i += 1
    return result, remaining


def _parse_install_args(args: List[str]) -> tuple[str, str, Any, Dict[str, str], Dict[str, str]]:
    if not args:
        raise ValueError("missing <name>")
    name = args[0]
    rest = args[1:]
    if not rest:
        raise ValueError('missing transport: use --stdio "<cmd>" or --sse <url>')

    flag = rest[0]
    if flag == "--stdio":
        if len(rest) < 2:
            raise ValueError("--stdio requires a command string")
        cmd = shlex.split(rest[1])
        if not cmd:
            raise ValueError("--stdio command is empty")
        env, _ = _parse_kv_flags(rest[2:], "env")
        return name, "stdio", cmd, {}, env
    if flag == "--sse":
        if len(rest) < 2:
            raise ValueError("--sse requires a URL")
        headers, _ = _parse_kv_flags(rest[2:], "header")
        return name, "sse", rest[1], headers, {}
    raise ValueError(f"unknown transport flag: {flag}")


def _try_online(method: str, path: str, *, json_body: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Return parsed JSON on 2xx, None if server offline.
    Aborts the process with a friendly error on 4xx/5xx so the caller can stay simple.
    """
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


def _cmd_install(args: List[str]) -> None:
    try:
        name, type_, target, headers, env = _parse_install_args(args)
    except ValueError as e:
        err_console.print(f"[red]Usage error:[/red] {e}")
        _help()
        sys.exit(1)

    body: Dict[str, Any] = {"name": name, "type": type_}
    if type_ == "stdio":
        body["command"] = target
        if env:
            body["env"] = env
    else:
        body["url"] = target
        if headers:
            body["headers"] = headers

    result = _try_online("POST", "/mcp/", json_body=body)
    if result is not None:
        console.print(f"[green]Installed[/green] [bold]{name}[/bold] ({type_})  [{_mode_tag()}]")
        console.print("[dim]Server has connected the adapter — tools are live.[/dim]")
        return

    data = _load_mcp_json()
    servers = data.setdefault("servers", {})
    if name in servers:
        err_console.print(f"[red]MCP server '{name}' already installed[/red]")
        sys.exit(1)
    if type_ == "stdio":
        entry: Dict[str, Any] = {"command": target}
        if env:
            entry["env"] = env
    else:
        entry = {"url": target}
        if headers:
            entry["headers"] = headers
    servers[name] = entry
    _save_mcp_json(data)
    console.print(f"[green]Installed[/green] [bold]{name}[/bold] ({type_})  [{_mode_tag()}]")
    console.print("[dim]Server not running — adapter will connect on next `waifu start`.[/dim]")


def _cmd_uninstall(args: List[str]) -> None:
    if not args:
        err_console.print("[red]Usage:[/red] waifu mcp uninstall <name>")
        sys.exit(1)
    name = args[0]

    result = _try_online("DELETE", f"/mcp/{name}")
    if result is not None:
        console.print(f"[green]Uninstalled[/green] [bold]{name}[/bold]  [{_mode_tag()}]")
        return

    data = _load_mcp_json()
    if name not in data.get("servers", {}):
        err_console.print(f"[red]MCP server '{name}' not found[/red]")
        sys.exit(1)
    del data["servers"][name]
    _save_mcp_json(data)
    console.print(f"[green]Uninstalled[/green] [bold]{name}[/bold]  [{_mode_tag()}]")


def _cmd_enable(args: List[str]) -> None:
    _toggle(args, action="enable", db_value=True)


def _cmd_disable(args: List[str]) -> None:
    _toggle(args, action="disable", db_value=False)


def _toggle(args: List[str], *, action: str, db_value: bool) -> None:
    if not args:
        err_console.print(f"[red]Usage:[/red] waifu mcp {action} <name>")
        sys.exit(1)
    name = args[0]

    result = _try_online("POST", f"/mcp/{name}/{action}")
    if result is not None:
        console.print(f"[green]{action.capitalize()}d[/green] [bold]{name}[/bold]  [{_mode_tag()}]")
        return

    data = _load_mcp_json()
    entry = data.get("servers", {}).get(name)
    if entry is None:
        err_console.print(f"[red]MCP server '{name}' not found[/red]")
        sys.exit(1)
    if db_value:
        entry.pop("enabled", None)
    else:
        entry["enabled"] = False
    _save_mcp_json(data)
    console.print(f"[green]{action.capitalize()}d[/green] [bold]{name}[/bold]  [{_mode_tag()}]")
    console.print("[dim]Applies on next `waifu start` (server not running).[/dim]")


def _cmd_search(args: List[str]) -> None:
    if not args:
        err_console.print("[red]Usage:[/red] waifu mcp search <query>")
        sys.exit(1)
    err_console.print(_REGISTRY_TODO)
