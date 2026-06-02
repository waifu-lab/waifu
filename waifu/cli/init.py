import sys
from typing import List

from rich.prompt import Confirm, Prompt

from waifu.cli._console import console, err_console
from waifu.store.paths import AppPaths

from hai.providers import PROVIDERS


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


def _selected_input(prompt: str, options: list[str], default: int = 1) -> str:
    # Interactive selector: navigate with arrow keys or WASD, Enter to choose.
    console.print(prompt)
    selected = max(0, min(len(options) - 1, default - 1))

    def _render():
        for i, opt in enumerate(options):
            if i == selected:
                sys.stdout.write(f"\x1b[2K> {i + 1}. {opt}\n")
            else:
                sys.stdout.write(f"\x1b[2K  {i + 1}. {opt}\n")
        sys.stdout.flush()

    try:
        _render()

        if sys.platform == "win32":
            import msvcrt

            while True:
                ch = msvcrt.getwch()
                if ch in ("\r", "\n"):
                    break
                if ch in ("\x00", "\xe0"):  # special key prefix
                    k = msvcrt.getwch()
                    if k == "H":  # up
                        selected = (selected - 1) % len(options)
                    elif k == "P":  # down
                        selected = (selected + 1) % len(options)
                else:
                    low = ch.lower()
                    if low == "w":
                        selected = (selected - 1) % len(options)
                    elif low == "s":
                        selected = (selected + 1) % len(options)

                # move cursor up and re-render
                sys.stdout.write(f"\x1b[{len(options)}A")
                _render()

        else:
            import termios, tty

            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setcbreak(fd)
                while True:
                    ch = sys.stdin.read(1)
                    if ch in ("\r", "\n"):
                        break
                    if ch == "\x1b":
                        seq = sys.stdin.read(2)
                        if seq == "[A":
                            selected = (selected - 1) % len(options)
                        elif seq == "[B":
                            selected = (selected + 1) % len(options)
                    else:
                        low = ch.lower()
                        if low == "w":
                            selected = (selected - 1) % len(options)
                        elif low == "s":
                            selected = (selected + 1) % len(options)

                    sys.stdout.write(f"\x1b[{len(options)}A")
                    _render()
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)

    except Exception:
        console.print()
        for index, option in enumerate(options, start=1):
            console.print(f"  {index}. {option}")
        raw = Prompt.ask("  Select", default=str(default))
        try:
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1]
        except Exception:
            pass
        err_console.print(f"[red]Invalid selection.[/red]")
        raise

    console.print()
    return options[selected]


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
    provider = _selected_input("  Provider:", [*PROVIDERS, "custom"])
    if not api_key.strip():
        err_console.print("[red]API key is required.[/red]")
        sys.exit(1)

    base_url = None if provider != "custom" else Prompt.ask("  Base URL (for custom provider)", default="").strip()
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
        provider=ProviderConfig(provider=provider, api_key=api_key, base_url=base_url, model=model),
        context=ContextConfig(system_prompt_template=system_prompt),
        gateway=GatewayConfig(host=host, port=port),
    )
    _write_config(config.model_dump(), cfg_file)

    _bootstrap_db(paths)

    console.print()
    console.print("[green][OK][/green] Setup complete.")
    console.print()
    console.print("  Start server  [bold]waifu start[/bold]")
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
