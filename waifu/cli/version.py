"""waifu version — show version info."""

from typing import List

from waifu import __version__
from waifu.cli._console import console


def cmd_version(_args: List[str]) -> None:
    console.print(f"[bold]waifu[/bold] [cyan]{__version__}[/cyan]")
