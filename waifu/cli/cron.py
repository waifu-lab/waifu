import sys
from datetime import datetime
from typing import List, Optional, cast

from rich.table import Table

from waifu.cli._console import console, err_console


def _get_store():
    from waifu.store import AppPaths, CronStore, Database

    paths = AppPaths.resolve()
    db = Database(paths.db_file)
    db.init()
    return CronStore()


def cmd_cron(args: List[str]) -> None:
    if not args or args[0] in ("-h", "--help"):
        _help()
        return

    sub = args[0]
    rest = args[1:]

    dispatch = {
        "list": _cmd_list,
        "add": _cmd_add,
        "remove": _cmd_remove,
        "run": _cmd_run,
        "enable": _cmd_enable,
        "disable": _cmd_disable,
        "history": _cmd_history,
    }

    if sub not in dispatch:
        err_console.print(f"[red]Unknown subcommand:[/red] {sub}")
        _help()
        sys.exit(1)

    dispatch[sub](rest)


def _help() -> None:
    console.print()
    console.print("[bold]waifu cron[/bold] — manage cron jobs")
    console.print()
    console.print("  [cyan]cron list[/cyan]                                  List cron jobs")
    console.print("  [cyan]cron add[/cyan] [green]<name> <type> <schedule> <command>[/green]  Add a job")
    console.print(
        "        type: [bold]at[/bold] <datetime>  |  [bold]every[/bold] <interval>  |  [bold]cron[/bold] <expr>"
    )
    console.print("  [cyan]cron remove[/cyan] [green]<id|name>[/green]                       Remove a job")
    console.print("  [cyan]cron run[/cyan] [green]<id|name>[/green]                          Run a job immediately")
    console.print("  [cyan]cron enable[/cyan] [green]<id|name>[/green]                       Enable a job")
    console.print("  [cyan]cron disable[/cyan] [green]<id|name>[/green]                      Disable a job")
    console.print("  [cyan]cron history[/cyan] [green]<id|name>[/green]                      Show run history")
    console.print()


def _resolve(store, id_or_name: str):
    """Resolve job by full id or name."""
    job = store.get(id_or_name) or store.get_by_name(id_or_name)
    if job is None:
        err_console.print(f"[red]Job not found:[/red] {id_or_name}")
        sys.exit(1)
    return job


def _cmd_list(args: List[str]) -> None:
    store = _get_store()
    jobs = store.list()
    if not jobs:
        console.print("[dim]No cron jobs configured.[/dim]")
        return
    table = Table(show_lines=False)
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Name", style="bold")
    table.add_column("Type")
    table.add_column("Schedule")
    table.add_column("Command")
    table.add_column("Enabled")
    for j in jobs:
        enabled = "[green][OK][/green]" if cast(bool, j.enabled) else "[dim]–[/dim]"
        table.add_row(
            cast(str, j.id)[:8],
            cast(str, j.name),
            cast(str, j.type),
            cast(str, j.schedule),
            cast(str, j.command)[:40],
            enabled,
        )
    console.print(table)


def _cmd_add(args: List[str]) -> None:
    # waifu cron add --name <name> --type <type> --schedule <schedule> --command <cmd>
    # also accepts positional: waifu cron add <name> <type> <schedule> <command...>
    import argparse

    if args and args[0].startswith("--"):
        p = argparse.ArgumentParser(prog="waifu cron add", add_help=False)
        p.add_argument("--name", required=True)
        p.add_argument("--type", dest="type_", required=True)
        p.add_argument("--schedule", required=True)
        p.add_argument("--command", required=True)
        try:
            ns = p.parse_args(args)
        except SystemExit:
            err_console.print(
                "[red]Usage:[/red] waifu cron add --name NAME --type TYPE --schedule SCHEDULE --command CMD"
            )
            sys.exit(1)
        name, type_, schedule, command = ns.name, ns.type_, ns.schedule, ns.command
    else:
        if len(args) < 4:
            err_console.print("[red]Usage:[/red] waifu cron add <name> <type> <schedule> <command>")
            err_console.print("  type: [bold]at[/bold] | [bold]every[/bold] | [bold]cron[/bold]")
            sys.exit(1)
        name, type_, schedule = args[0], args[1], args[2]
        command = " ".join(args[3:])
    if type_ not in ("at", "every", "cron"):
        err_console.print(f"[red]Invalid type:[/red] {type_}  (must be at | every | cron)")
        sys.exit(1)
    store = _get_store()
    job = store.create(name=name, type=type_, schedule=schedule, command=command)
    console.print(
        f"[green][OK][/green] Job [bold]{cast(str, job.name)}[/bold] created  [dim]{cast(str, job.id)[:8]}[/dim]"
    )


def _cmd_remove(args: List[str]) -> None:
    if not args:
        err_console.print("[red]Usage:[/red] waifu cron remove <id|name>")
        sys.exit(1)
    store = _get_store()
    job = _resolve(store, args[0])
    store.remove(cast(str, job.id))
    console.print(f"[green][OK][/green] Removed [bold]{cast(str, job.name)}[/bold]")


def _cmd_run(args: List[str]) -> None:
    if not args:
        err_console.print("[red]Usage:[/red] waifu cron run <id|name>")
        sys.exit(1)
    import subprocess

    store = _get_store()
    job = _resolve(store, args[0])
    run = store.start_run(cast(str, job.id))
    console.print(f"Running [bold]{cast(str, job.name)}[/bold]…")
    try:
        result = subprocess.run(cast(str, job.command), shell=True, capture_output=True, text=True)
        output = result.stdout + result.stderr
        status = "success" if result.returncode == 0 else "error"
        store.finish_run(cast(str, run.id), status=status, output=output)
        if output:
            console.print(output.rstrip())
        style = "green" if status == "success" else "red"
        console.print(f"[{style}]Done ({status}, exit {result.returncode})[/{style}]")
    except Exception as exc:
        store.finish_run(cast(str, run.id), status="error", output=str(exc))
        err_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


def _cmd_enable(args: List[str]) -> None:
    if not args:
        err_console.print("[red]Usage:[/red] waifu cron enable <id|name>")
        sys.exit(1)
    store = _get_store()
    job = _resolve(store, args[0])
    store.enable(cast(str, job.id))
    console.print(f"[green][OK][/green] Enabled [bold]{cast(str, job.name)}[/bold]")


def _cmd_disable(args: List[str]) -> None:
    if not args:
        err_console.print("[red]Usage:[/red] waifu cron disable <id|name>")
        sys.exit(1)
    store = _get_store()
    job = _resolve(store, args[0])
    store.disable(cast(str, job.id))
    console.print(f"[yellow]–[/yellow] Disabled [bold]{cast(str, job.name)}[/bold]")


def _cmd_history(args: List[str]) -> None:
    if not args:
        err_console.print("[red]Usage:[/red] waifu cron history <id|name>")
        sys.exit(1)
    store = _get_store()
    job = _resolve(store, args[0])
    runs = store.history(cast(str, job.id))
    if not runs:
        console.print("[dim]No runs yet.[/dim]")
        return
    table = Table(title=f"History: {cast(str, job.name)}", show_lines=False)
    table.add_column("Run ID", style="dim", no_wrap=True)
    table.add_column("Started", style="dim")
    table.add_column("Finished", style="dim")
    table.add_column("Status")
    for r in runs:
        status = cast(str, r.status)
        status_fmt = {
            "success": "[green]success[/green]",
            "error": "[red]error[/red]",
            "running": "[yellow]running[/yellow]",
        }.get(status, status)
        table.add_row(
            cast(str, r.id)[:8],
            str(cast(datetime, r.started_at))[:16],
            str(cast(Optional[datetime], r.finished_at))[:16] if cast(Optional[datetime], r.finished_at) else "—",
            status_fmt,
        )
    console.print(table)
