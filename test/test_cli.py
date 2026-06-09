"""Tests for the waifu CLI.

Tier breakdown:
  unit    — CLI argument routing / help text (no subprocess, calls cmd_* directly)
  offline — subprocess invocations that don't need a running server or LLM
  online  — CLI commands that talk to a running waifu server (skipped if offline)

Subprocess tests invoke the `waifu` entry-point script directly.
They are skipped automatically if `waifu` is not installed in the current env
(run `uv sync` first to make the script available).
"""
import shutil
import subprocess
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _waifu_exe() -> str | None:
    """Return the path to the `waifu` executable, or None if not installed."""
    return shutil.which("waifu")


def run_cli(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run `waifu` CLI as a subprocess; skips if not installed."""
    exe = _waifu_exe()
    if exe is None:
        pytest.skip("`waifu` not found in PATH — run `uv sync` first")
    return subprocess.run(
        [exe, *args],
        capture_output=True,
        text=True,
        check=check,
    )


# ---------------------------------------------------------------------------
# Unit — argument routing (calls Python functions directly, no subprocess)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_cli_main_no_args_prints_help(capsys):
    """waifu (no args) prints help text without error."""
    import sys

    with patch.object(sys, "argv", ["waifu"]):
        from waifu.cli import main
        main()

    captured = capsys.readouterr()
    assert "waifu" in captured.out.lower() or "command" in captured.out.lower()


@pytest.mark.unit
def test_cli_config_routes_to_list(monkeypatch):
    """'waifu config list' calls _cmd_list without raising."""
    calls: list = []
    import waifu.cli.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_cmd_list", lambda: calls.append("list"))
    cfg_mod.cmd_config(["list"])
    assert calls == ["list"]


@pytest.mark.unit
def test_cli_config_get_requires_path(capsys):
    with pytest.raises(SystemExit):
        from waifu.cli.config import cmd_config
        cmd_config(["get"])


@pytest.mark.unit
def test_cli_config_set_requires_two_args(capsys):
    with pytest.raises(SystemExit):
        from waifu.cli.config import cmd_config
        cmd_config(["set", "only_one_arg"])


@pytest.mark.unit
def test_cli_unknown_command_exits():
    import sys

    with patch.object(sys, "argv", ["waifu", "nonexistent_cmd_xyz"]):
        from waifu.cli import main
        with pytest.raises(SystemExit):
            main()


# ---------------------------------------------------------------------------
# Offline — subprocess CLI (reads from real config file; no server needed)
# ---------------------------------------------------------------------------

@pytest.mark.offline
def test_cli_subprocess_help():
    result = run_cli()
    assert result.returncode == 0
    assert "waifu" in result.stdout.lower()


@pytest.mark.offline
def test_cli_version():
    result = run_cli("version")
    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert output.strip() != ""


@pytest.mark.offline
def test_cli_config_list_offline():
    """config list in offline mode reads config.toml and prints it."""
    result = run_cli("config", "list")
    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert output.strip() != ""


@pytest.mark.offline
def test_cli_config_get_provider_model():
    result = run_cli("config", "get", "provider.model")
    assert result.returncode == 0
    assert result.stdout.strip() != ""


@pytest.mark.offline
def test_cli_skill_list():
    result = run_cli("skill", "list")
    assert result.returncode == 0


@pytest.mark.offline
def test_cli_mcp_list():
    result = run_cli("mcp", "list")
    assert result.returncode == 0


@pytest.mark.offline
def test_cli_cron_list():
    result = run_cli("cron", "list")
    assert result.returncode == 0


@pytest.mark.offline
def test_cli_conversations_list():
    result = run_cli("conversations")
    assert result.returncode == 0


@pytest.mark.offline
def test_cli_character_list():
    result = run_cli("character", "list")
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Online — CLI interacts with a running waifu server
# ---------------------------------------------------------------------------

@pytest.mark.online
def test_cli_config_set_online():
    """config set goes through the server API when the server is running."""
    result = run_cli("config", "set", "provider.temperature", "0.7")
    assert result.returncode == 0
    assert "0.7" in result.stdout


@pytest.mark.online
def test_cli_cron_add_and_remove():
    """cron add / remove round-trip via the running server."""
    import uuid

    job_name = f"cli_test_{uuid.uuid4().hex[:6]}"
    add_result = run_cli(
        "cron", "add",
        "--name", job_name,
        "--type", "every",
        "--schedule", "1h",
        "--command", "echo cli_cron_test",
    )
    assert add_result.returncode == 0, add_result.stderr

    rm_result = run_cli("cron", "remove", job_name)
    assert rm_result.returncode == 0, rm_result.stderr
