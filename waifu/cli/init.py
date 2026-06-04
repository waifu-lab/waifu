import sys
from pathlib import Path
from typing import Any, List, Optional

from rich.prompt import Confirm, Prompt

from hai.providers import PROVIDERS
from waifu.cli._console import console, err_console
from waifu.config import (
    ContextConfig,
    GatewayConfig,
    ProviderConfig,
    STTConfig,
    TTSConfig,
    VoiceConfig,
    WaifuConfig,
    WaifuNodeConfig,
)
from waifu.gateway.config import build_builtin_gateway_adapter_registry
from waifu.store.paths import AppPaths

_PROVIDER_BASE_URL_DEFAULTS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/chat/completions",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "ollama": "http://localhost:11434/v1/chat/completions",
}

_PROVIDER_MODEL_DEFAULTS = {
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-5",
    "google": "gemini-2.5-flash",
    "ollama": "llama3.2",
}


def _masked_input(prompt: str) -> str:  # noqa: C901
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
            import termios
            import tty

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


def _selected_input(prompt: str, options: list[str], default: int = 1) -> str:  # noqa: C901
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
            import termios
            import tty

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
        err_console.print("[red]Invalid selection.[/red]")
        raise

    console.print()
    return options[selected]


def _prompt_required_str(prompt: str, default: Optional[str] = None) -> str:
    while True:
        if default is None:
            raw = Prompt.ask(prompt).strip()
        else:
            raw = Prompt.ask(prompt, default=default).strip()
        if raw:
            return raw
        err_console.print("[red]Value is required.[/red]")


def _prompt_optional_str(prompt: str, default: Optional[str] = None) -> Optional[str]:
    raw = Prompt.ask(prompt, default=default or "").strip()
    return raw or None


def _prompt_int(prompt: str, default: Optional[int] = None) -> Optional[int]:
    while True:
        raw = Prompt.ask(prompt, default="" if default is None else str(default)).strip()
        if raw == "":
            return None
        try:
            return int(raw)
        except ValueError:
            err_console.print("[red]Please enter an integer.[/red]")


def _prompt_float(prompt: str, default: float) -> float:
    while True:
        raw = Prompt.ask(prompt, default=str(default)).strip()
        try:
            return float(raw)
        except ValueError:
            err_console.print("[red]Please enter a number.[/red]")


def _provider_default_index(default_provider: str) -> int:
    options = [*PROVIDERS, "custom"]
    try:
        return options.index(default_provider) + 1
    except ValueError:
        return 1


def _prompt_provider_config(title: str, *, default_provider: str = "openai", default_temperature: float = 0.7):
    console.rule(f"[dim]{title}[/dim]")
    console.print()
    provider = _selected_input(
        "  Provider:",
        [*PROVIDERS, "custom"],
        default=_provider_default_index(default_provider),
    )
    api_key = _masked_input("  API key (leave blank for Ollama/local): ").strip()
    if not api_key and provider not in ("ollama", "custom"):
        if not Confirm.ask("  API key is empty. Continue anyway?", default=False):
            err_console.print("[red]API key is required for this provider.[/red]")
            sys.exit(1)

    base_url_default = _PROVIDER_BASE_URL_DEFAULTS.get(provider, "")
    base_url = _prompt_optional_str("  Base URL", default=base_url_default)
    if provider == "custom" and not base_url:
        err_console.print("[red]Base URL is required for custom provider.[/red]")
        sys.exit(1)

    model = _prompt_required_str("  Model", default=_PROVIDER_MODEL_DEFAULTS.get(provider))
    temperature = _prompt_float("  Temperature", default=default_temperature)
    max_tokens = _prompt_int("  Max tokens (blank = provider default)", default=None)

    return ProviderConfig(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _prompt_character(characters_dir: Path) -> Optional[str]:
    characters = sorted(d.name for d in characters_dir.iterdir() if d.is_dir()) if characters_dir.exists() else []
    if characters:
        options = ["(none)", *characters]
        selected = _selected_input("  Active character:", options)
        return None if selected == "(none)" else selected
    return _prompt_optional_str("  Active character (blank = none)")


def _prompt_voice_config():
    console.rule("[dim]Voice[/dim]")
    console.print()
    if not Confirm.ask("  Configure voice features?", default=False):
        return None

    stt = None
    tts = None

    if Confirm.ask("  Enable STT (speech to text)?", default=False):
        console.print("\n  [bold]STT[/bold]")
        stt_api_key = _masked_input("  STT API key: ").strip()
        stt_base_url = Prompt.ask(
            "  STT Base URL",
            default="https://api.openai.com/v1/audio/transcriptions",
        ).strip()
        stt_model = Prompt.ask("  STT Model", default="whisper-1").strip()
        stt_language = _prompt_optional_str("  STT Language (blank = auto, e.g. zh/en)")
        stt_temperature = _prompt_float("  STT Temperature", default=0.0)
        stt = STTConfig(
            api_key=stt_api_key,
            base_url=stt_base_url,
            model=stt_model,
            language=stt_language,
            temperature=stt_temperature,
        )

    if Confirm.ask("  Enable TTS (text to speech)?", default=False):
        console.print("\n  [bold]TTS[/bold]")
        tts_api_key = _masked_input("  TTS API key: ").strip()
        tts_base_url = Prompt.ask(
            "  TTS Base URL",
            default="https://api.openai.com/v1/audio/speech",
        ).strip()
        tts_model = Prompt.ask("  TTS Model", default="tts-1").strip()
        tts_voice = _selected_input(
            "  TTS Voice:",
            ["alloy", "echo", "fable", "onyx", "nova", "shimmer"],
            default=5,
        )
        tts = TTSConfig(
            api_key=tts_api_key,
            base_url=tts_base_url,
            model=tts_model,
            voice=tts_voice,
        )

    if stt is None and tts is None:
        return None
    return VoiceConfig(stt=stt, tts=tts)


def _strip_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_strip_none(item) for item in value]
    return value


def cmd_init(args: List[str]) -> None:
    del args
    paths = AppPaths.resolve()
    cfg_file = paths.config_file

    console.print()
    console.print("[bold]waifu init[/bold]")
    console.print()
    console.print(f"  Config : [dim]{cfg_file}[/dim]")
    console.print(f"  Gateway: [dim]{paths.gateway_config_file}[/dim]")
    console.print(f"  DB     : [dim]{paths.db_file}[/dim]")
    console.print()

    overwrite = False
    if cfg_file.exists():
        console.print("[yellow]Config already exists.[/yellow]")
        overwrite = Confirm.ask("Overwrite?", default=False)
        if not overwrite:
            # Still init DB in case it's missing
            if not paths.gateway_config_file.exists():
                _write_gateway_config(
                    build_builtin_gateway_adapter_registry().create_default_config(),
                    paths.gateway_config_file,
                )
            _bootstrap_db(paths)
            console.print("[dim]Config unchanged. DB ready.[/dim]")
            return

    provider_config = _prompt_provider_config("Provider")

    console.rule("[dim]Persona[/dim]")
    system_prompt = "You are a helpful assistant."
    character = _prompt_character(paths.characters_dir)

    console.rule("[dim]Context[/dim]")
    max_history_messages = _prompt_int("\n  Max history messages", default=20) or 20
    history_strategy = _selected_input("  History strategy:", ["sliding", "summary", "full"])
    context_token_budget = _prompt_int("  Context token budget (blank = unlimited)", default=None)
    compact_threshold = _prompt_float("  Compact threshold", default=0.85)

    console.rule("[dim]Gateway[/dim]")
    host = Prompt.ask("\n  Host", default="0.0.0.0")
    port = _prompt_int("  Port", default=8765) or 8765
    session_ttl = _prompt_int("  Session TTL seconds", default=3600) or 3600
    lane_max_queue = _prompt_int("  Lane max queue", default=10) or 10

    utility_provider = None
    if Confirm.ask("\nConfigure a separate utility provider?", default=False):
        utility_provider = _prompt_provider_config(
            "Utility provider",
            default_provider=provider_config.provider,
            default_temperature=0.3,
        )

    voice = _prompt_voice_config()

    console.rule("[dim]Waifu-Node[/dim]")
    console.print()

    node_enabled = Confirm.ask("  Enable Waifu-Node local control adapter?", default=False)
    node_token = _masked_input("  Node token (blank = no auth): ").strip()
    node_invoke_timeout_ms = _prompt_int("  Node invoke timeout ms", default=10000) or 10000

    config = WaifuConfig(
        provider=provider_config,
        utility_provider=utility_provider,
        context=ContextConfig(
            system_prompt_template=system_prompt,
            max_history_messages=max_history_messages,
            history_strategy=history_strategy,  # type: ignore[arg-type]
            context_token_budget=context_token_budget,
            compact_threshold=compact_threshold,
        ),
        gateway=GatewayConfig(
            host=host,
            port=port,
            session_ttl=session_ttl,
            lane_max_queue=lane_max_queue,
        ),
        voice=voice,
        node=WaifuNodeConfig(
            enabled=node_enabled,
            token=node_token,
            invoke_timeout_ms=node_invoke_timeout_ms,
        ),
        character=character,
    )
    _write_config(config.model_dump(exclude_none=True), cfg_file)
    _write_gateway_config(
        build_builtin_gateway_adapter_registry().create_default_config(),
        paths.gateway_config_file,
    )

    _bootstrap_db(paths)

    console.print()
    console.print("[green][OK][/green] Setup complete.")
    console.print()
    console.print("  Start server  [bold]waifu start[/bold]")
    console.print()


def _write_config(data: dict, path: Path) -> None:
    import tomli_w

    with open(path, "wb") as f:
        tomli_w.dump(_strip_none(data), f)
    console.print(f"[dim]Config written → {path}[/dim]")


def _write_gateway_config(config, path: Path) -> None:
    config.save(path)
    console.print(f"[dim]Gateway written ??{path}[/dim]")


def _bootstrap_db(paths: AppPaths) -> None:
    from waifu.store.models import Database

    db = Database(paths.db_file)
    db.init()
    db.close()
    console.print(f"[dim]DB ready        → {paths.db_file}[/dim]")
