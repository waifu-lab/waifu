import sys
from pathlib import Path
from typing import List

from rich.table import Table

from waifu.card import CardImporter, CardParser
from waifu.cli._console import console, err_console
from waifu.service.character import CharacterService
from waifu.store import AppPaths, CharacterManager, Database
from waifu.store.repositories import CharacterRepository, RelationshipRepository


def cmd_character(args: List[str]) -> None:
    if not args or args[0] in ("-h", "--help"):
        _help()
        return

    sub = args[0]
    rest = args[1:]

    if sub == "import-card":
        _cmd_import_card(rest)
        return
    if sub == "import-cards":
        _cmd_import_cards(rest)
        return

    err_console.print(f"[red]Unknown subcommand:[/red] {sub}")
    _help()
    sys.exit(1)


def _help() -> None:
    console.print()
    console.print("[bold]waifu character[/bold] manage characters")
    console.print()
    console.print("  [cyan]character import-card[/cyan] [green]<path> [--overwrite][/green]   Import one card")
    console.print("  [cyan]character import-cards[/cyan] [green][--overwrite][/green]          Import all cards/ files")
    console.print()


def _build_service() -> CharacterService:
    paths = AppPaths.resolve()
    db = Database(paths.db_file)
    db.init()
    return CharacterService(
        CharacterRepository(),
        RelationshipRepository(),
        manager=CharacterManager(paths.characters_dir),
        card_importer=CardImporter(cards_dir=paths.cards_dir, parser=CardParser()),
    )


def _cmd_import_card(args: List[str]) -> None:
    overwrite = False
    cleaned: list[str] = []
    for arg in args:
        if arg == "--overwrite":
            overwrite = True
        else:
            cleaned.append(arg)
    if not cleaned:
        err_console.print("[red]Usage:[/red] waifu character import-card <path> [--overwrite]")
        sys.exit(1)

    service = _build_service()
    result = service.import_card(Path(cleaned[0]), overwrite=overwrite)
    console.print(f"[green][OK][/green] {result.status} [bold]{result.name}[/bold]")
    console.print(f"  soul   [dim]{result.soul_path}[/dim]")
    if result.avatar_path is not None:
        console.print(f"  avatar [dim]{result.avatar_path}[/dim]")


def _cmd_import_cards(args: List[str]) -> None:
    overwrite = "--overwrite" in args
    service = _build_service()
    results, errors = service.import_all_cards(overwrite=overwrite)

    table = Table(show_lines=False)
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Source", style="dim")
    for result in results:
        table.add_row(result.name, result.status, str(result.source_path))
    if results:
        console.print(table)
    else:
        console.print("[dim]No cards found.[/dim]")

    for path, exc in errors:
        err_console.print(f"[red]Import failed:[/red] {path}  {exc}")
