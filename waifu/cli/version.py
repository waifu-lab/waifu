import argparse
import json
import sys
from typing import List

from waifu import __version__
from waifu.cli._console import console


def cmd_version(args: List[str]) -> None:
    parser = argparse.ArgumentParser(prog="waifu version", description="Show version")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    ns = parser.parse_args(args)

    if ns.json:
        info = {
            "version": __version__,
            "python": ".".join(map(str, sys.version_info[:3])),
            "frozen": bool(getattr(sys, "frozen", False)),
        }
        print(json.dumps(info))
        return

    console.print(f"[bold]waifu[/bold] [cyan]{__version__}[/cyan]")
