import sys
from datetime import datetime
from typing import List, cast

from rich.table import Table

from waifu.cli._console import console, err_console


def _get_store():
    from waifu.store import AppPaths, ConversationStore, Database

    paths = AppPaths.resolve()
    db = Database(paths.db_file)
    db.init()
    return ConversationStore(
        conversations_dir=paths.conversations_dir,
        attachments_dir=paths.attachments_dir,
    )


def cmd_conversation(cmd: str, args: List[str]) -> None:
    if cmd == "conversations":
        limit = int(args[0]) if args and args[0].isdigit() else 20
        _cmd_list(limit)
        return

    if not args or args[0] in ("-h", "--help"):
        _help()
        return

    sub = args[0]
    rest = args[1:]

    dispatch = {
        "create": _cmd_create,
        "delete": _cmd_delete,
        "search": _cmd_search,
        "compact": _cmd_compact,
        "messages": _cmd_messages,
        "export": _cmd_export,
    }

    if sub not in dispatch:
        err_console.print(f"[red]Unknown subcommand:[/red] {sub}")
        _help()
        sys.exit(1)

    dispatch[sub](rest)


def _help() -> None:
    console.print()
    console.print("[bold]waifu conversation[/bold] — manage conversations")
    console.print()
    console.print("  [cyan]conversations[/cyan] [green][limit][/green]                  List recent conversations")
    console.print("  [cyan]conversation create[/cyan] [green]<title>[/green]            Create a new conversation")
    console.print("  [cyan]conversation delete[/cyan] [green]<id>[/green]               Delete a conversation")
    console.print("  [cyan]conversation search[/cyan] [green]<query>[/green]            Search by id, title or content")
    console.print("  [cyan]conversation compact[/cyan] [green]<id>[/green]          Compact conversation context")
    console.print("  [cyan]conversation messages[/cyan] [green]<id> [limit][/green]  Show messages")
    console.print("  [cyan]conversation export[/cyan] [green]<id> [path][/green]     Export conversation to markdown")
    console.print()


def _cmd_list(limit: int) -> None:
    store = _get_store()
    convs = store.list(limit)
    if not convs:
        console.print("[dim]No conversations yet.[/dim]")
        return
    table = Table(show_lines=False)
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Title", style="bold")
    table.add_column("Updated", style="dim")
    for c in convs:
        table.add_row(cast(str, c.id), cast(str, c.title), str(cast(datetime, c.updated_at))[:16])
    console.print(table)


def _cmd_create(args: List[str]) -> None:
    if not args:
        err_console.print("[red]Usage:[/red] waifu conversation create <title>")
        sys.exit(1)
    title = " ".join(args)
    store = _get_store()
    c = store.create(title)
    console.print(f"[green][OK][/green] Created [bold]{c.title}[/bold]  [dim]{c.id}[/dim]")


def _cmd_delete(args: List[str]) -> None:
    if not args:
        err_console.print("[red]Usage:[/red] waifu conversation delete <id>")
        sys.exit(1)
    store = _get_store()
    ok = store.delete(args[0])
    if ok:
        console.print(f"[green][OK][/green] Deleted [dim]{args[0]}[/dim]")
    else:
        err_console.print(f"[red]Not found:[/red] {args[0]}")
        sys.exit(1)


def _cmd_search(args: List[str]) -> None:
    if not args:
        err_console.print("[red]Usage:[/red] waifu conversation search <query>")
        sys.exit(1)
    query = " ".join(args)
    store = _get_store()
    convs = store.search(query)
    if not convs:
        console.print(f'[dim]No results for "{query}"[/dim]')
        return
    table = Table(show_lines=False)
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Title", style="bold")
    table.add_column("Updated", style="dim")
    for c in convs:
        table.add_row(cast(str, c.id), cast(str, c.title), str(cast(datetime, c.updated_at))[:16])
    console.print(table)


def _cmd_compact(args: List[str]) -> None:
    if not args:
        err_console.print("[red]Usage:[/red] waifu conversation compact <id>")
        sys.exit(1)
    store = _get_store()
    n = store.compact(args[0])
    console.print(f"[green][OK][/green] Removed {n} message(s) from [dim]{args[0]}[/dim]")


def _render_parts(content: str) -> str:
    """Convert JSON parts to a human-readable string."""
    import json

    try:
        parts = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content
    lines = []
    for p in parts:
        t = p.get("type", "")
        if t == "text":
            lines.append(p.get("text", ""))
        elif t == "tool-result":
            lines.append(f"  [dim]↳ result:[/dim] {p.get('result', '')!r}")
        elif t.startswith("tool-"):
            name = p.get("toolName") or t[5:]
            args = p.get("args", {})
            lines.append(f"  [yellow]⚙ {name}[/yellow]  [dim]{args}[/dim]")
    return "\n".join(lines)


def _cmd_messages(args: List[str]) -> None:
    if not args:
        err_console.print("[red]Usage:[/red] waifu conversation messages <id> [limit]")
        sys.exit(1)
    id_prefix = args[0]
    limit = int(args[1]) if len(args) > 1 and args[1].isdigit() else 50
    store = _get_store()
    conv = store.resolve(id_prefix)
    if conv is None:
        err_console.print(f"[red]Not found (or ambiguous):[/red] {id_prefix}")
        sys.exit(1)
    msgs = store.get_messages(cast(str, conv.id), limit)
    if not msgs:
        console.print("[dim]No messages.[/dim]")
        return
    for m in msgs:
        role = cast(str, m.role)
        role_color = {"user": "cyan", "assistant": "green", "tool": "yellow"}.get(role, "white")
        console.print(
            f"[bold {role_color}]{role}[/bold {role_color}]  [dim]{str(cast(datetime, m.created_at))[:16]}[/dim]"
        )
        console.print(_render_parts(cast(str, m.content)))
        console.print()


def _cmd_export(args: List[str]) -> None:
    if not args:
        err_console.print("[red]Usage:[/red] waifu conversation export <id> [path]")
        sys.exit(1)
    from pathlib import Path

    from waifu.store import AppPaths, ConversationStore, Database
    from waifu.store.conversation import _safe_filename

    id_prefix = args[0]
    paths = AppPaths.resolve()
    db = Database(paths.db_file)
    db.init()
    store = ConversationStore(
        conversations_dir=paths.conversations_dir,
        attachments_dir=paths.attachments_dir,
    )
    conv = store.resolve(id_prefix)
    if conv is None:
        err_console.print(f"[red]Not found (or ambiguous):[/red] {id_prefix}")
        sys.exit(1)
    if len(args) > 1:
        dest = Path(args[1])
    else:
        dest = paths.conversations_dir / _safe_filename(cast(str, conv.title), cast(str, conv.id))
    out = store.export_markdown(cast(str, conv.id), dest)
    console.print(f"[green][OK][/green] Exported → [dim]{out}[/dim]")
