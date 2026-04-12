import sys
from typing import List

from rich.prompt import Confirm, Prompt

from waifu.cli._console import console, err_console
from waifu.store.paths import AppPaths


def _masked_input(prompt: str) -> str:
    """Read a line of input, echoing '*' for each character (cross-platform)."""
    console.print(prompt, end="")
    chars: list[str] = []
    try:
        if sys.platform == "win32":
            import msvcrt

            while True:
                ch = msvcrt.getwch()
                if ch in ("\r", "\n"):
                    break
                if ch == "\x03":  # Ctrl-C
                    raise KeyboardInterrupt
                if ch in ("\x08", "\x7f"):  # backspace
                    if chars:
                        chars.pop()
                        sys.stdout.write("\b \b")
                else:
                    chars.append(ch)
                    sys.stdout.write("*")
                sys.stdout.flush()
            sys.stdout.write("\n")
        else:
            import termios, tty

            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                while True:
                    ch = sys.stdin.read(1)
                    if ch in ("\r", "\n"):
                        break
                    if ch == "\x03":
                        raise KeyboardInterrupt
                    if ch in ("\x08", "\x7f"):
                        if chars:
                            chars.pop()
                            sys.stdout.write("\b \b")
                    else:
                        chars.append(ch)
                        sys.stdout.write("*")
                    sys.stdout.flush()
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            sys.stdout.write("\n")
    except (ImportError, Exception):
        import getpass

        return getpass.getpass("")
    return "".join(chars)


def cmd_init(args: List[str]) -> None:
    paths = AppPaths.resolve()
    cfg_file = paths.config_file

    console.print()
    console.print("[bold]waifu init[/bold]")
    console.print()
    console.print(f"  Config : [dim]{cfg_file}[/dim]")
    console.print(f"  DB     : [dim]{paths.db_file}[/dim]")
    console.print()

    overwrite = False
    if cfg_file.exists():
        console.print("[yellow]Config already exists.[/yellow]")
        overwrite = Confirm.ask("Overwrite?", default=False)
        if not overwrite:
            # Still init DB in case it's missing
            _bootstrap_db(paths)
            console.print("[dim]Config unchanged. DB ready.[/dim]")
            return

    console.rule("[dim]Provider[/dim]")
    console.print()
    api_key = _masked_input("  API key: ")
    if not api_key.strip():
        err_console.print("[red]API key is required.[/red]")
        sys.exit(1)

    base_url = Prompt.ask("  Base URL", default="https://api.openai.com/v1")
    model = Prompt.ask("  Model", default="gpt-4o")

    console.rule("[dim]Persona[/dim]")
    system_prompt = Prompt.ask(
        "\n  System prompt",
        default="You are a helpful assistant.",
    )

    console.rule("[dim]Gateway[/dim]")
    host = Prompt.ask("\n  Host", default="0.0.0.0")
    port = int(Prompt.ask("  Port", default="8765"))

    from waifu.config import ContextConfig, GatewayConfig, ProviderConfig, WaifuConfig

    config = WaifuConfig(
        provider=ProviderConfig(api_key=api_key, base_url=base_url, model=model),
        context=ContextConfig(system_prompt_template=system_prompt),
        gateway=GatewayConfig(host=host, port=port),
    )
    _write_config(config.model_dump(), cfg_file)

    _bootstrap_db(paths)

    console.print()
    console.print("[green][OK][/green] Setup complete.")
    console.print()
    console.print("  Start server  [bold]waifu start[/bold]")
    console.print('  Chat (CLI)    [bold]waifu run "hello"[/bold]')
    console.print("  Chat (TUI)    [bold]waifu tui[/bold]")
    console.print()


def _write_config(data: dict, path) -> None:
    import tomli_w

    with open(path, "wb") as f:
        tomli_w.dump(data, f)
    console.print(f"[dim]Config written → {path}[/dim]")


def _bootstrap_db(paths: AppPaths) -> None:
    from waifu.store.models import Database

    db = Database(paths.db_file)
    db.init()
    db.close()
    console.print(f"[dim]DB ready        → {paths.db_file}[/dim]")
