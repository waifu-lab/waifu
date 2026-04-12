import sys
from typing import List

from rich.table import Table

from waifu.cli._console import console, err_console

_TODO = "[yellow]TODO:[/yellow] requires MCP registry integration"


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
        "search": _cmd_search,
        "find": _cmd_search,  # alias
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
    console.print("  [cyan]mcp list[/cyan]                   List configured MCP servers")
    console.print("  [cyan]mcp install[/cyan] [green]<source>[/green]      Install an MCP server")
    console.print("  [cyan]mcp uninstall[/cyan] [green]<name>[/green]      Remove an MCP server")
    console.print("  [cyan]mcp search[/cyan] [green]<query>[/green]        Search MCP registry")
    console.print("  [cyan]mcp find[/cyan] [green]<query>[/green]          Alias for search")
    console.print()


def _cmd_list(args: List[str]) -> None:
    from waifu.cli.config import _load_raw

    raw = _load_raw()
    mcp_section = raw.get("mcp", {})

    if not mcp_section:
        console.print("[dim]No MCP servers configured.[/dim]")
        console.print(f"[dim]Add servers to [bold]~/.waifu/config.toml[/bold] under [mcp.<name>][/dim]")
        return

    table = Table(title="MCP Servers", show_lines=False)
    table.add_column("Name", style="bold cyan")
    table.add_column("Type")
    table.add_column("Command / URL")

    for name, cfg in mcp_section.items():
        if isinstance(cfg, dict):
            kind = cfg.get("type", "stdio")
            cmd_or_url = cfg.get("cmd") or cfg.get("url") or str(cfg)
            if isinstance(cmd_or_url, list):
                cmd_or_url = " ".join(cmd_or_url)
            table.add_row(name, kind, cmd_or_url)

    console.print(table)


def _cmd_install(args: List[str]) -> None:
    if not args:
        err_console.print("[red]Usage:[/red] waifu mcp install <source>")
        sys.exit(1)
    err_console.print(_TODO)


def _cmd_uninstall(args: List[str]) -> None:
    if not args:
        err_console.print("[red]Usage:[/red] waifu mcp uninstall <name>")
        sys.exit(1)
    err_console.print(_TODO)


def _cmd_search(args: List[str]) -> None:
    if not args:
        err_console.print("[red]Usage:[/red] waifu mcp search <query>")
        sys.exit(1)
    err_console.print(_TODO)
