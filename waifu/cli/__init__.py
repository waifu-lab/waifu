import sys

from rich.table import Table
from rich.text import Text

from waifu.cli._console import console, err_console

_COMMANDS = [
    ("init", None, "First-run setup (config + DB)"),
    ("start", None, "Start the waifu server"),
    ("version", None, "Show version"),
    ("config", ["get", "set", "list"], "Read or update settings"),
    (
        "character",
        ["list", "use", "import-card", "import-cards", "sync-card", "sync-cards"],
        "Manage characters and cards",
    ),
    ("conversations", None, "List recent conversations"),
    ("conversation", ["create", "delete", "search", "compact", "messages"], "Manage conversations"),
    ("skill", ["list", "search", "find", "install", "update", "uninstall"], "Manage skills"),
    ("mcp", ["list", "install", "uninstall", "search", "find"], "Manage MCP servers"),
    ("cron", ["list", "add", "remove", "run", "enable", "disable", "history"], "Manage cron jobs"),
]


def _print_help() -> None:
    console.print()
    console.print(Text("waifu", style="bold magenta") + Text("  — AI assistant server & CLI"))
    console.print()

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column(style="dim")
    table.add_column()

    for cmd, subs, desc in _COMMANDS:
        sub_str = f"[dim][{', '.join(subs)}][/dim]" if subs else ""
        table.add_row(cmd, sub_str, desc)

    console.print(table)
    console.print()
    console.print("  Run [bold]waifu <command> --help[/bold] for details on a specific command.")
    console.print()


def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        _print_help()
        return

    cmd = args[0]
    rest = args[1:]

    if cmd == "init":
        from waifu.cli.init import cmd_init

        cmd_init(rest)

    elif cmd == "start":
        from waifu.cli.start import cmd_start

        cmd_start(rest)

    elif cmd == "version":
        from waifu.cli.version import cmd_version

        cmd_version(rest)

    elif cmd == "config":
        from waifu.cli.config import cmd_config

        cmd_config(rest)

    elif cmd == "character":
        from waifu.cli.character import cmd_character

        cmd_character(rest)

    elif cmd in ("conversations", "conversation"):
        from waifu.cli.conversation import cmd_conversation

        cmd_conversation(cmd, rest)

    elif cmd == "skill":
        from waifu.cli.skill import cmd_skill

        cmd_skill(rest)

    elif cmd == "mcp":
        from waifu.cli.mcp import cmd_mcp

        cmd_mcp(rest)

    elif cmd == "cron":
        from waifu.cli.cron import cmd_cron

        cmd_cron(rest)

    else:
        err_console.print(f"[red]Unknown command:[/red] {cmd}")
        _print_help()
        sys.exit(1)
