import json
import os
import subprocess
import sys
import time
import urllib.request

import pytest

pytestmark = pytest.mark.offline

_CLI = [sys.executable, "-c", "from waifu.cli import main; main()"]


@pytest.fixture
def env(tmp_path):
    e = dict(os.environ)
    e["WAIFU_CONFIG_DIR"] = str(tmp_path / "cfg")
    e["WAIFU_DATA_DIR"] = str(tmp_path / "data")
    e["PYTHONIOENCODING"] = "utf-8"
    e.pop("WAIFU_PARENT_PID", None)
    return e


def _run(env, *args, **kwargs):
    return subprocess.run(
        [*_CLI, *args], env=env, capture_output=True, text=True, encoding="utf-8", timeout=60, **kwargs
    )


def _init_ok(env):
    e = {**env, "WAIFU_API_KEY": "sk-test"}
    proc = _run(e, "init", "--non-interactive", "--provider", "openai", "--model", "gpt-4o-mini")
    assert proc.returncode == 0, proc.stderr
    return proc


def test_version_json(env):
    proc = _run(env, "version", "--json")
    assert proc.returncode == 0, proc.stderr
    info = json.loads(proc.stdout)
    from waifu import __version__

    assert info["version"] == __version__
    assert info["frozen"] is False


def test_init_non_interactive_writes_config(env, tmp_path):
    _init_ok(env)
    text = (tmp_path / "cfg" / "config.toml").read_text(encoding="utf-8")
    assert 'model = "gpt-4o-mini"' in text
    assert 'api_key = "sk-test"' in text


def test_init_non_interactive_requires_api_key(env):
    proc = _run(env, "init", "--non-interactive", "--provider", "openai")
    assert proc.returncode == 2
    assert "API key" in proc.stderr


def test_init_non_interactive_keeps_existing_without_force(env, tmp_path):
    _init_ok(env)
    proc = _run({**env, "WAIFU_API_KEY": "sk-other"}, "init", "-y")
    assert proc.returncode == 0
    assert 'api_key = "sk-test"' in (tmp_path / "cfg" / "config.toml").read_text(encoding="utf-8")

    proc = _run({**env, "WAIFU_API_KEY": "sk-other"}, "init", "-y", "--force")
    assert proc.returncode == 0
    assert 'api_key = "sk-other"' in (tmp_path / "cfg" / "config.toml").read_text(encoding="utf-8")


def test_init_without_tty_refuses_to_prompt(env):
    proc = _run(env, "init", stdin=subprocess.DEVNULL)
    assert proc.returncode == 2
    assert "--non-interactive" in proc.stderr


def _start(env, *args):
    return subprocess.Popen(
        [*_CLI, "start", "--host", "127.0.0.1", "--port", "0", *args],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )


def _wait_ready(proc, timeout=60.0) -> dict:
    deadline = time.monotonic() + timeout
    assert proc.stdout is not None
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        if line.startswith("WAIFU_READY "):
            return json.loads(line[len("WAIFU_READY ") :])
    pytest.fail("server did not print WAIFU_READY")


def test_start_port_zero_prints_ready_line(env):
    _init_ok(env)
    proc = _start(env)
    try:
        ready = _wait_ready(proc)
        assert ready["port"] > 0
        # 不一定等於 proc.pid：Windows venv 的 python.exe 與 PyInstaller onefile 都會再啟一個子程序
        assert isinstance(ready["pid"], int)
        with urllib.request.urlopen(f"{ready['url']}/health", timeout=5) as resp:
            body = json.loads(resp.read())
        assert body == {"status": "ok", "version": ready["version"]}
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_start_exits_when_parent_dies(env):
    _init_ok(env)
    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    proc = _start(env, "--parent-pid", str(parent.pid))
    try:
        _wait_ready(proc)
        assert proc.poll() is None
        parent.kill()
        parent.wait(timeout=10)
        proc.wait(timeout=20)
        assert proc.returncode is not None
    finally:
        parent.kill()
        proc.kill()
