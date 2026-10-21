import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from importlib import metadata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from loguru import logger

DEPS_DIRNAME = ".deps"
_STAMP = ".waifu-deps.json"
_BUNDLED_CONSTRAINTS = Path(__file__).with_name("bundled-constraints.txt")

_PLATFORMS = {
    ("win32", "amd64"): "x86_64-pc-windows-msvc",
    ("win32", "arm64"): "aarch64-pc-windows-msvc",
    ("darwin", "x86_64"): "x86_64-apple-darwin",
    ("darwin", "arm64"): "aarch64-apple-darwin",
    ("linux", "x86_64"): "x86_64-unknown-linux-gnu",
    ("linux", "aarch64"): "aarch64-unknown-linux-gnu",
}


class PluginDependencyError(RuntimeError):
    pass


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_name(req: str) -> str:
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", req)
    if not match:
        raise PluginDependencyError(f"Invalid requirement: {req!r}")
    return normalize(match.group(1))


def host_constraints() -> Dict[str, str]:
    """``{normalized name: version}`` of packages the host provides."""
    if not _BUNDLED_CONSTRAINTS.exists():
        return installed_constraints()
    result = {}
    for line in _BUNDLED_CONSTRAINTS.read_text(encoding="utf-8").splitlines():
        if "==" in line and not line.lstrip().startswith("#"):
            name, version = line.split("==", 1)
            result[normalize(name)] = version.strip()
    return result


def installed_constraints() -> Dict[str, str]:
    result = {}
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if not name or dist.read_text("direct_url.json"):
            continue
        result[normalize(name)] = dist.version
    return result


def python_target() -> Tuple[str, str]:
    machine = platform.machine().lower()
    plat = _PLATFORMS.get((sys.platform, machine))
    if plat is None:
        raise PluginDependencyError(f"Unsupported platform for plugin dependencies: {sys.platform}/{machine}")
    return f"{sys.version_info.major}.{sys.version_info.minor}", plat


def find_uv() -> Optional[str]:
    if env := os.environ.get("WAIFU_UV"):
        return env
    exe_name = "uv.exe" if sys.platform == "win32" else "uv"
    if getattr(sys, "frozen", False):
        bundled = Path(sys.executable).with_name(exe_name)
        if bundled.exists():
            return str(bundled)
    return shutil.which("uv")


class PluginDependencyInstaller:
    def __init__(self, uv: Optional[str] = None, constraints: Optional[Dict[str, str]] = None) -> None:
        self._uv = uv
        self._constraints = constraints

    def _host(self) -> Dict[str, str]:
        if self._constraints is None:
            self._constraints = host_constraints()
        return self._constraints

    def ensure(self, plugin_dir: Path, dependencies: List[str]) -> Optional[Path]:
        """Install ``dependencies`` if not already satisfied; return the deps dir (None if nothing to add)."""
        deps_dir = plugin_dir / DEPS_DIRNAME
        host = self._host()

        extra: List[str] = []
        for req in dependencies:
            name = _requirement_name(req)
            if name in host:
                logger.debug("Plugin dependency {} is provided by host ({})", req, host[name])
            else:
                extra.append(req)

        if not extra:
            if deps_dir.exists():
                shutil.rmtree(deps_dir)
            return None

        pyver, plat = python_target()
        stamp = {"dependencies": sorted(extra), "python": pyver, "platform": plat, "host": self._host_hash()}
        if self._read_stamp(deps_dir) == stamp:
            return deps_dir

        self._install(deps_dir, extra, pyver, plat)
        (deps_dir / _STAMP).write_text(json.dumps(stamp), encoding="utf-8")
        return deps_dir

    def _host_hash(self) -> str:
        data = "\n".join(f"{k}=={v}" for k, v in sorted(self._host().items()))
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    @staticmethod
    def _read_stamp(deps_dir: Path) -> Optional[dict]:
        try:
            return json.loads((deps_dir / _STAMP).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _install(self, deps_dir: Path, requirements: List[str], pyver: str, plat: str) -> None:
        uv = self._uv or find_uv()
        if uv is None:
            raise PluginDependencyError("uv not found (put uv next to the waifu binary, on PATH, or set WAIFU_UV)")

        staging = deps_dir.with_name(DEPS_DIRNAME + ".tmp")
        if staging.exists():
            shutil.rmtree(staging)

        with tempfile.TemporaryDirectory() as tmp:
            constraints_file = Path(tmp) / "constraints.txt"
            constraints_file.write_text(
                "\n".join(f"{k}=={v}" for k, v in sorted(self._host().items())) + "\n", encoding="utf-8"
            )
            cmd = [
                uv, "pip", "install",
                "--target", str(staging),
                "--python-version", pyver,
                "--python-platform", plat,
                "--constraint", str(constraints_file),
                *requirements,
            ]  # fmt: skip
            logger.info("Installing plugin dependencies: {}", " ".join(requirements))
            proc = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
        if proc.returncode != 0:
            shutil.rmtree(staging, ignore_errors=True)
            raise PluginDependencyError(f"uv pip install failed:\n{proc.stderr.strip()}")

        self._prune_host_packages(staging)
        if deps_dir.exists():
            shutil.rmtree(deps_dir)
        staging.rename(deps_dir)

    def _prune_host_packages(self, target: Path) -> None:
        """Remove distributions the host already provides (same pinned version, host copy wins anyway)."""
        host = self._host()
        for dist_info in target.glob("*.dist-info"):
            name = dist_info.name[: -len(".dist-info")].rsplit("-", 1)[0]
            if normalize(name) not in host:
                continue
            record = dist_info / "RECORD"
            if record.exists():
                for line in record.read_text(encoding="utf-8").splitlines():
                    rel = line.split(",", 1)[0]
                    path = target / rel
                    if rel and path.is_file():
                        path.unlink()
            shutil.rmtree(dist_info, ignore_errors=True)

        for path in sorted(target.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()


def write_bundled_constraints(path: Path) -> None:
    lines = [f"{k}=={v}" for k, v in sorted(installed_constraints().items())]
    header = "# Generated at build time: packages bundled in the waifu binary\n"
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
