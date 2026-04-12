import sys
from typing import List

from waifu.cli._console import console, err_console

_TODO = "[yellow]TODO:[/yellow] requires skills registry integration (skills.sh / GitHub)"


def cmd_skill(args: List[str]) -> None:
    if not args or args[0] in ("-h", "--help"):
        _help()
        return

    sub = args[0]
    rest = args[1:]

    dispatch = {
        "list": _cmd_list,
        "search": _cmd_search,
        "find": _cmd_search,  # alias
        "install": _cmd_install,
        "update": _cmd_update,
        "uninstall": _cmd_uninstall,
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
    console.print("  [cyan]skill search[/cyan] [green]<query>[/green]         Search skills (via skills.sh)")
    console.print("  [cyan]skill find[/cyan] [green]<query>[/green]           Alias for search")
    console.print("  [cyan]skill install[/cyan] [green]<source>[/green]       Install a skill (skills.sh or GitHub)")
    console.print("  [cyan]skill update[/cyan]                  Check and update installed skills")
    console.print("  [cyan]skill uninstall[/cyan] [green]<name>[/green]       Remove an installed skill")
    console.print()


def _cmd_list(args: List[str]) -> None:
    err_console.print(_TODO)


def _cmd_search(args: List[str]) -> None:
    if not args:
        err_console.print("[red]Usage:[/red] waifu skill search <query>")
        sys.exit(1)
    err_console.print(_TODO)


def _cmd_install(args: List[str]) -> None:
    if not args:
        err_console.print("[red]Usage:[/red] waifu skill install <source>")
        sys.exit(1)
    err_console.print(_TODO)


def _cmd_update(args: List[str]) -> None:
    err_console.print(_TODO)


def _cmd_uninstall(args: List[str]) -> None:
    if not args:
        err_console.print("[red]Usage:[/red] waifu skill uninstall <name>")
        sys.exit(1)
    err_console.print(_TODO)
