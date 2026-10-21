import json
import sys
from pathlib import Path

import pytest

from waifu.plugin.deps import DEPS_DIRNAME, PluginDependencyInstaller, normalize
from waifu.plugin.loader import PluginLoader

pytestmark = pytest.mark.unit

HOST = {"pydantic": "2.13.4", "pydantic-core": "2.41.0", "httpx": "0.28.1"}


class _RecordingInstaller(PluginDependencyInstaller):
    """Replaces the uv call with a fake that creates the target dir."""

    def __init__(self) -> None:
        super().__init__(uv="uv", constraints=dict(HOST))
        self.calls = []

    def _install(self, deps_dir, requirements, pyver, plat):  # noqa: ARG002
        self.calls.append(list(requirements))
        deps_dir.mkdir(parents=True, exist_ok=True)


def test_normalize():
    assert normalize("Pydantic_Core") == "pydantic-core"
    assert normalize("ruamel.yaml") == "ruamel-yaml"


def test_host_provided_dependencies_are_not_installed(tmp_path):
    inst = _RecordingInstaller()
    assert inst.ensure(tmp_path, ["pydantic>=2", "HTTPX"]) is None
    assert inst.calls == []


def test_extra_dependencies_installed_once_then_stamped(tmp_path):
    inst = _RecordingInstaller()
    deps = inst.ensure(tmp_path, ["orjson>=3", "pydantic"])
    assert deps == tmp_path / DEPS_DIRNAME
    assert inst.calls == [["orjson>=3"]]

    inst.ensure(tmp_path, ["orjson>=3", "pydantic"])
    assert inst.calls == [["orjson>=3"]]  # stamp matches → no reinstall


def test_reinstall_when_dependencies_or_host_change(tmp_path):
    inst = _RecordingInstaller()
    inst.ensure(tmp_path, ["orjson"])
    inst.ensure(tmp_path, ["orjson", "humanize"])
    assert len(inst.calls) == 2

    inst._constraints = {**HOST, "pydantic": "2.99.0"}
    inst.ensure(tmp_path, ["orjson", "humanize"])
    assert len(inst.calls) == 3


def test_removing_all_extra_dependencies_deletes_deps_dir(tmp_path):
    inst = _RecordingInstaller()
    inst.ensure(tmp_path, ["orjson"])
    assert (tmp_path / DEPS_DIRNAME).exists()
    inst.ensure(tmp_path, [])
    assert not (tmp_path / DEPS_DIRNAME).exists()


def _fake_dist(target: Path, name: str, version: str, files: dict) -> None:
    info = target / f"{name}-{version}.dist-info"
    info.mkdir(parents=True)
    record = []
    for rel, content in files.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        record.append(f"{rel},,")
    (info / "METADATA").write_text(f"Name: {name}\nVersion: {version}\n")
    record.append(f"{info.name}/METADATA,,")
    (info / "RECORD").write_text("\n".join(record))


def test_prune_removes_host_packages_only(tmp_path):
    _fake_dist(tmp_path, "pydantic_core", "2.41.0", {"pydantic_core/__init__.py": "", "pydantic_core/core.pyd": "x"})
    _fake_dist(tmp_path, "orjson", "3.13.0", {"orjson/__init__.py": ""})

    PluginDependencyInstaller(constraints=dict(HOST))._prune_host_packages(tmp_path)

    assert not (tmp_path / "pydantic_core").exists()
    assert not (tmp_path / "pydantic_core-2.41.0.dist-info").exists()
    assert (tmp_path / "orjson" / "__init__.py").exists()
    assert (tmp_path / "orjson-3.13.0.dist-info").exists()


def test_loader_appends_deps_dir_after_host_paths(tmp_path, monkeypatch):
    plugin_dir = tmp_path / "demo"
    (plugin_dir / DEPS_DIRNAME / "demo_extra").mkdir(parents=True)
    (plugin_dir / DEPS_DIRNAME / "demo_extra" / "__init__.py").write_text("VALUE = 42\n")
    (plugin_dir / "__init__.py").write_text(
        "from waifu_types import BasePlugin\n"
        "import demo_extra\n"
        "class Demo(BasePlugin):\n"
        "    name = 'demo'\n"
        "    async def on_load(self, ctx):\n"
        "        pass\n"
    )
    (plugin_dir / "metadata.json").write_text(
        json.dumps({"name": "demo", "version": "1", "entry": "demo.Demo", "dependencies": ["orjson"]})
    )
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.delitem(sys.modules, "demo", raising=False)
    monkeypatch.delitem(sys.modules, "demo_extra", raising=False)

    loader = PluginLoader(tmp_path, _RecordingInstaller())
    assert loader.read_meta("demo").dependencies == ["orjson"]
    plugin = loader.resolve("demo")

    assert plugin.name == "demo"
    assert sys.path[-1] == str(plugin_dir / DEPS_DIRNAME)
