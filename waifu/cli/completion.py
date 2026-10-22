import codecs
import locale
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, cast

from waifu.cli._console import console, err_console

_SHELLS = ("bash", "zsh", "fish", "powershell")
_BLOCK_BEGIN = "# >>> waifu completion >>>"
_BLOCK_END = "# <<< waifu completion <<<"

_FLAGS: Dict[Tuple[str, ...], List[str]] = {
    ("start",): ["--config", "-c", "--host", "--port", "-p", "--app", "--reload", "--log-level", "--debug"],
    ("character", "import-card"): ["--overwrite"],
    ("character", "import-cards"): ["--overwrite"],
}


_FLAG_VALUES: Dict[str, List[str]] = {
    "--config": [],
    "-c": [],
    "--host": [],
    "--port": [],
    "-p": [],
    "--app": [],
    "--log-level": ["trace", "debug", "info", "warning", "error", "critical"],
}


_FILE_ARGS = {("character", "import-card"), ("character", "sync-card")}


def _conversation_ids() -> List[str]:
    from waifu.cli.conversation import _get_store

    return [cast(str, c.id) for c in _get_store().list(50)]


def _character_names() -> List[str]:
    from waifu.cli.character import _build_service

    return _build_service().list_available_characters()


def _skill_names() -> List[str]:
    from waifu.skill.loader import scan_skills
    from waifu.store import AppPaths

    return [s.name for s in scan_skills(AppPaths.resolve().skills_dir)]


def _mcp_names() -> List[str]:
    from waifu.cli.mcp import _list_offline

    return [row["name"] for row in _list_offline()]


def _cron_names() -> List[str]:
    from waifu.cli.cron import _get_store

    return [cast(str, j.name) for j in _get_store().list()]


def _config_keys() -> List[str]:
    from waifu.cli.config import _load_raw
    from waifu.config.sync import flatten

    return list(flatten(_load_raw()))


_PROVIDERS: Dict[Tuple[str, ...], Callable[[], List[str]]] = {
    **{("conversation", s): _conversation_ids for s in ("delete", "compact", "messages", "export")},
    ("character", "use"): _character_names,
    **{("skill", s): _skill_names for s in ("update", "uninstall")},
    **{("mcp", s): _mcp_names for s in ("uninstall", "enable", "disable")},
    **{("cron", s): _cron_names for s in ("remove", "run", "enable", "disable", "history")},
    **{("config", s): _config_keys for s in ("get", "set")},
    **{("completion", s): lambda: list(_SHELLS) for s in ("install", "uninstall")},
}


def _subcommands() -> Dict[str, List[str]]:
    from waifu.cli import _COMMANDS

    subs = {name: list(s or []) for name, s, _ in _COMMANDS}
    subs["conversations"] = []
    return subs


def _raw_candidates(prev: List[str], cur: str) -> List[str]:
    subs = _subcommands()
    if not prev:
        return ["--help"] if cur.startswith("-") else [*subs, "help"]

    cmd = prev[0]
    if cmd not in subs:
        return []
    if prev[-1] in _FLAG_VALUES:
        return _FLAG_VALUES[prev[-1]]
    if subs[cmd] and len(prev) == 1:
        return ["--help"] if cur.startswith("-") else subs[cmd]

    path = (cmd, prev[1]) if subs[cmd] else (cmd,)
    flags = _FLAGS.get(path, [])
    if cur.startswith("-"):
        return [*flags, "--help"]

    positional = [w for w in prev[len(path) :] if not w.startswith("-")]
    if positional or path in _FILE_ARGS:
        return []
    provider = _PROVIDERS.get(path)
    if provider is None:
        return flags
    from loguru import logger

    logger.remove()
    try:
        return provider()
    except Exception:
        return []


def candidates(words: List[str]) -> List[str]:
    *prev, cur = words or [""]
    return list(dict.fromkeys(c for c in _raw_candidates(prev, cur) if c.startswith(cur)))


def cmd_complete(args: List[str]) -> None:
    words = list(args)
    if words:
        words[-1] = words[-1][1:] if words[-1].startswith("_") else words[-1]
    _write_lf("".join(f"{c}\n" for c in candidates(words)))


def cmd_completion(args: List[str]) -> None:
    if not args or args[0] in ("-h", "--help"):
        _help()
        return
    if args[0] in ("install", "uninstall"):
        shell = _parse_shell(args[1]) if len(args) > 1 else _detect_shell()
        if shell is None:
            err_console.print("[red]Cannot detect shell.[/red] Specify one: " + ", ".join(_SHELLS))
            sys.exit(1)
        (_install if args[0] == "install" else _uninstall)(shell)
        return
    shell = _parse_shell(args[0])
    if shell is None:
        err_console.print(f"[red]Unsupported shell:[/red] {args[0]}  (choose from: {', '.join(_SHELLS)})")
        sys.exit(1)
    _write_lf(_SCRIPTS[shell]())


def _parse_shell(name: str) -> Optional[str]:
    name = name.lower()
    if name in ("pwsh", "powershell"):
        return "powershell"
    return name if name in _SHELLS else None


def _detect_shell() -> Optional[str]:
    shell = _parse_shell(Path(os.environ.get("SHELL", "")).stem)
    if shell is not None:
        return shell
    return "powershell" if sys.platform == "win32" else None


def _rc_files(shell: str) -> List[Path]:
    home = Path.home()
    if shell == "bash":
        return [home / ".bashrc"]
    if shell == "zsh":
        return [Path(os.environ.get("ZDOTDIR") or home) / ".zshrc"]
    if shell == "fish":
        return [Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "fish" / "completions" / "waifu.fish"]
    return _powershell_profiles()


def _powershell_profiles() -> List[Path]:
    profiles: List[Path] = []
    for exe in ("powershell", "pwsh"):
        if shutil.which(exe) is None:
            continue
        try:
            out = subprocess.run(
                [exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "$PROFILE.CurrentUserAllHosts"],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
        if out:
            profiles.append(Path(out))
    return list(dict.fromkeys(profiles))


def _install(shell: str) -> None:
    targets = _rc_files(shell)
    if not targets:
        err_console.print(f"[red]Cannot locate config file for {shell}.[/red]")
        sys.exit(1)
    script = _SCRIPTS[shell]()
    for path in targets:
        if shell == "fish":
            _write_text(path, script, "utf-8", "\n")
        else:
            text, encoding, newline = _read_text(path, shell)
            _write_text(path, with_block(text, script), encoding, newline)
        console.print(f"[green][OK][/green] Installed {shell} completion to [dim]{path}[/dim]")
    console.print("  note   [dim]restart your shell to enable it[/dim]")


def _uninstall(shell: str) -> None:
    removed = False
    for path in _rc_files(shell):
        if not path.exists():
            continue
        if shell == "fish":
            path.unlink()
        else:
            text, encoding, newline = _read_text(path, shell)
            stripped = without_block(text)
            if stripped is None:
                continue
            _write_text(path, stripped, encoding, newline)
        removed = True
        console.print(f"[green][OK][/green] Removed {shell} completion from [dim]{path}[/dim]")
    if not removed:
        console.print(f"[dim]{shell} completion is not installed.[/dim]")


def with_block(text: str, script: str) -> str:
    body = (without_block(text) or text).rstrip("\n")
    block = f"{_BLOCK_BEGIN}\n{script.rstrip()}\n{_BLOCK_END}\n"
    return f"{body}\n\n{block}" if body else block


def without_block(text: str) -> Optional[str]:
    """移除 waifu 區塊；沒有區塊時回傳 None"""
    lines = text.split("\n")
    if _BLOCK_BEGIN not in (line.strip() for line in lines):
        return None
    kept: List[str] = []
    inside = False
    for line in lines:
        if line.strip() == _BLOCK_BEGIN:
            inside = True
        elif line.strip() == _BLOCK_END:
            inside = False
        elif not inside:
            kept.append(line)
    body = "\n".join(kept).rstrip("\n")
    return f"{body}\n" if body else ""


def _read_text(path: Path, shell: str) -> Tuple[str, str, str]:
    raw = path.read_bytes() if path.exists() else b""
    if raw.startswith(codecs.BOM_UTF8):
        encoding = "utf-8-sig"
    elif raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encoding = "utf-16"
    else:
        encoding = "utf-8"
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        encoding = locale.getpreferredencoding(False)
        text = raw.decode(encoding, errors="replace")
    if "\r\n" in text or (not text and shell == "powershell"):
        newline = "\r\n"
    else:
        newline = "\n"
    return text.replace("\r\n", "\n"), encoding, newline


def _write_text(path: Path, text: str, encoding: str, newline: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\n", newline).encode(encoding))


def _write_lf(text: str) -> None:
    sys.stdout.buffer.write(text.encode(sys.stdout.encoding or "utf-8", errors="replace"))
    sys.stdout.flush()


def _help() -> None:
    console.print()
    console.print("[bold]waifu completion[/bold] — shell completion")
    console.print()
    console.print("  [cyan]completion install[/cyan] [green]\\[shell][/green]    Install into your shell config")
    console.print("  [cyan]completion uninstall[/cyan] [green]\\[shell][/green]  Remove from your shell config")
    console.print("  [cyan]completion[/cyan] [green]<shell>[/green]              Print the script")
    console.print()
    console.print(f"  shells: [dim]{', '.join(_SHELLS)}[/dim]")
    console.print()


def _bash() -> str:
    return r"""# waifu bash completion
_waifu_completion() {
    local line="${COMP_LINE:0:COMP_POINT}"
    local -a words prev
    read -a words <<< "$line"
    local cur="" n=${#words[@]} i
    if [[ -n "$line" && "$line" != *[[:space:]] ]]; then
        cur="${words[n-1]}"
        prev=("${words[@]:1:n-2}")
    else
        prev=("${words[@]:1}")
    fi
    local IFS=$'\n'
    COMPREPLY=($(waifu __complete "${prev[@]}" "_$cur" 2>/dev/null))
    if [[ "$cur" == *:* && "$COMP_WORDBREAKS" == *:* ]]; then
        local colon_prefix="${cur%"${cur##*:}"}"
        for i in "${!COMPREPLY[@]}"; do
            COMPREPLY[i]="${COMPREPLY[i]#"$colon_prefix"}"
        done
    fi
    for i in "${!COMPREPLY[@]}"; do
        COMPREPLY[i]=$(printf '%q' "${COMPREPLY[i]}")
    done
}
complete -o default -F _waifu_completion waifu
"""


def _zsh() -> str:
    return r"""# waifu zsh completion
_waifu() {
    local -a candidates
    candidates=("${(@f)$(waifu __complete "${(@)words[2,CURRENT-1]}" "_${words[CURRENT]}" 2>/dev/null)}")
    candidates=(${candidates:#})
    if (( ${#candidates} )); then
        compadd -- "${candidates[@]}"
    else
        _files
    fi
}
(( $+functions[compdef] )) || { autoload -Uz compinit && compinit }
compdef _waifu waifu
"""


def _fish() -> str:
    file_args = " ".join(f'"{" ".join(p)}"' for p in sorted(_FILE_ARGS))
    return f"""# waifu fish completion
function __waifu_complete
    set -l prev (commandline -opc)
    set -e prev[1]
    set -l cur (commandline -ct)
    waifu __complete $prev "_$cur" 2>/dev/null
end

function __waifu_needs_file
    set -l prev (commandline -opc)
    test (count $prev) -eq 3; and contains -- "$prev[2] $prev[3]" {file_args}
end

complete -c waifu -f -a '(__waifu_complete)'
complete -c waifu -n __waifu_needs_file -F
"""


def _powershell() -> str:
    return r"""# waifu PowerShell completion
Register-ArgumentCompleter -Native -CommandName waifu -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)
    $prev = @($commandAst.CommandElements | Select-Object -Skip 1 |
        Where-Object { $_.Extent.EndOffset -lt $cursorPosition } |
        ForEach-Object { $_.Extent.Text })
    & waifu __complete @prev "_$wordToComplete" 2>$null | ForEach-Object {
        $text = if ($_ -match '\s') { "'$($_ -replace "'", "''")'" } else { $_ }
        [System.Management.Automation.CompletionResult]::new($text, $_, 'ParameterValue', $_)
    }
}
"""


_SCRIPTS: Dict[str, Callable[[], str]] = {"bash": _bash, "zsh": _zsh, "fish": _fish, "powershell": _powershell}
