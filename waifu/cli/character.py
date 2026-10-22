import sys
from pathlib import Path
from typing import Any, List, Optional, cast

import tomli_w
from rich.table import Table

from waifu.card import CardImporter, CardParser
from waifu.cli._console import console, err_console
from waifu.cli.init import _selected_input
from waifu.service.character import CharacterService
from waifu.store import AppPaths, CharacterManager, Database
from waifu.store.repositories import AppConfigRepository, CharacterRepository, RelationshipRepository


def cmd_character(args: List[str]) -> None:
    if not args or args[0] in ("-h", "--help"):
        _help()
        return

    sub = args[0]
    rest = args[1:]

    if sub == "list":
        _cmd_list()
        return
    if sub == "use":
        _cmd_use(rest)
        return
    if sub == "import-card":
        _cmd_import_card(rest)
        return
    if sub == "import-cards":
        _cmd_import_cards(rest)
        return
    if sub == "sync-card":
        _cmd_sync_card(rest)
        return
    if sub == "sync-cards":
        _cmd_sync_cards(rest)
        return

    err_console.print(f"[red]Unknown subcommand:[/red] {sub}")
    _help()
    sys.exit(1)


def _help() -> None:
    console.print()
    console.print("[bold]waifu character[/bold] manage characters")
    console.print()
    console.print("  [cyan]character list[/cyan]                                         List available characters")
    console.print(
        "  [cyan]character use[/cyan] [green][name-or-id|--none][/green]              Select active character"
    )
    console.print("  [cyan]character import-card[/cyan] [green]<path> [--overwrite][/green]   Import one card")
    console.print("  [cyan]character import-cards[/cyan] [green][--overwrite][/green]          Import all cards/ files")
    console.print("  [cyan]character sync-card[/cyan] [green]<path>[/green]                    Force sync one card")
    console.print("  [cyan]character sync-cards[/cyan]                                  Force sync all cards/ files")
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


def _load_config(paths: AppPaths) -> dict[str, Any]:
    config_path = paths.config_file
    if not config_path.exists():
        return {}

    import tomllib

    with open(config_path, "rb") as f:
        data = tomllib.load(f)
    return data if isinstance(data, dict) else {}


def _save_config(paths: AppPaths, data: dict[str, Any]) -> None:
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    with open(paths.config_file, "wb") as f:
        tomli_w.dump(data, f)


def _set_selected_character(paths: AppPaths, name: Optional[str]) -> None:
    data = _load_config(paths)
    if name is None:
        data.pop("character", None)
    else:
        data["character"] = name
    _save_config(paths, data)

    repo = AppConfigRepository()
    if name is None:
        repo.delete("character")
    else:
        repo.set("character", name)


def _current_selected_character(paths: AppPaths) -> Optional[str]:
    value = _load_config(paths).get("character")
    return value if isinstance(value, str) and value.strip() else None


def _cmd_list() -> None:
    paths = AppPaths.resolve()
    service = _build_service()
    selected = _current_selected_character(paths)
    active = service.get_active()
    rows = []
    db_rows = {cast(str, char.name): char for char in service.list_all()}
    for name in service.list_available_characters():
        row = db_rows.get(name)
        has_files = (paths.characters_dir / name).is_dir()
        if row is not None and has_files:
            source = "db + files"
        elif row is not None:
            source = "db"
        else:
            source = "files"
        rows.append((name, selected == name, active is not None and active.name == name, source))

    if not rows:
        console.print("[dim]No characters found.[/dim]")
        if selected:
            console.print(f"[yellow]Selected in config but missing:[/yellow] {selected}")
        return

    table = Table(show_lines=False)
    table.add_column("Name", style="bold")
    table.add_column("Selected")
    table.add_column("DB Active")
    table.add_column("Source")
    for name, is_selected, is_active, source in rows:
        table.add_row(name, "yes" if is_selected else "", "yes" if is_active else "", source)
    console.print(table)
    if selected and selected not in {name for name, _, _, _ in rows}:
        console.print(f"[yellow]Selected in config but missing:[/yellow] {selected}")


def _cmd_use(args: List[str]) -> None:
    paths = AppPaths.resolve()
    service = _build_service()

    if args and args[0] == "--none":
        service.clear_active()
        _set_selected_character(paths, None)
        console.print(f"[green][OK][/green] Cleared selected character [dim]({paths.config_file})[/dim]")
        return

    if args:
        ref = " ".join(args).strip()
    else:
        names = service.list_available_characters()
        if not names:
            err_console.print("[red]No characters found.[/red] Import a card first.")
            sys.exit(1)
        ref = _selected_input("  Active character:", ["(none)", *names])
        if ref == "(none)":
            service.clear_active()
            _set_selected_character(paths, None)
            console.print(f"[green][OK][/green] Cleared selected character [dim]({paths.config_file})[/dim]")
            return

    character = service.select_character(ref)
    _set_selected_character(paths, cast(str, character.name))
    console.print(f"[green][OK][/green] Selected [bold]{character.name}[/bold]")
    console.print(f"  config [dim]{paths.config_file}[/dim]")
    console.print("  note   [dim]takes effect on next `waifu start`[/dim]")


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


def _cmd_sync_card(args: List[str]) -> None:
    if len(args) != 1:
        err_console.print("[red]Usage:[/red] waifu character sync-card <path>")
        sys.exit(1)

    service = _build_service()
    result = service.sync_card(Path(args[0]))
    console.print(f"[green][OK][/green] {result.status} [bold]{result.name}[/bold]")
    console.print(f"  soul   [dim]{result.soul_path}[/dim]")
    if result.avatar_path is not None:
        console.print(f"  avatar [dim]{result.avatar_path}[/dim]")


def _cmd_sync_cards(args: List[str]) -> None:
    if args:
        err_console.print("[red]Usage:[/red] waifu character sync-cards")
        sys.exit(1)

    service = _build_service()
    results, errors = service.sync_all_cards()

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
        err_console.print(f"[red]Sync failed:[/red] {path}  {exc}")
