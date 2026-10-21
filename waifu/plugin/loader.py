import importlib.util
import json
import sys
from pathlib import Path
from typing import List, Optional

from waifu.plugin.deps import DEPS_DIRNAME, PluginDependencyInstaller
from waifu_types import BasePlugin


class PluginMeta:
    def __init__(self, dir: Path, data: dict) -> None:
        self.dir = dir
        self.name = data["name"]
        self.version = data["version"]
        self.description = data.get("description", "")
        self.entry = data["entry"]  # "module.ClassName"
        self.config_schema = data.get("config_schema", {})
        self.dependencies: List[str] = data.get("dependencies", [])  # PEP 508, e.g. "orjson>=3"


class PluginLoader:
    def __init__(self, plugins_dir: Path, deps: PluginDependencyInstaller) -> None:
        self._dir = plugins_dir
        self._deps = deps

    def list_available(self) -> List[PluginMeta]:
        result = []
        if not self._dir.exists():
            return result
        for p in self._dir.iterdir():
            meta_file = p / "metadata.json"
            if p.is_dir() and meta_file.exists():
                try:
                    result.append(PluginMeta(p, json.loads(meta_file.read_text(encoding="utf-8"))))
                except (KeyError, json.JSONDecodeError):
                    pass
        return result

    def read_meta(self, plugin_name: str) -> PluginMeta:
        meta_file = self._dir / plugin_name / "metadata.json"
        if not meta_file.exists():
            raise FileNotFoundError(f"Plugin '{plugin_name}' not found or missing metadata.json")
        return PluginMeta(self._dir / plugin_name, json.loads(meta_file.read_text(encoding="utf-8")))

    def ensure_dependencies(self, plugin_name: str) -> Optional[Path]:
        """Install the plugin's declared dependencies if needed (blocking; may hit the network)."""
        meta = self.read_meta(plugin_name)
        return self._deps.ensure(meta.dir, meta.dependencies)

    def resolve(self, plugin_name: str) -> BasePlugin:
        meta = self.read_meta(plugin_name)
        module_path, class_name = meta.entry.rsplit(".", 1)

        plugin_parent = str(meta.dir.parent)
        if plugin_parent not in sys.path:
            sys.path.insert(0, plugin_parent)

        deps_dir = meta.dir / DEPS_DIRNAME
        if deps_dir.is_dir() and str(deps_dir) not in sys.path:
            sys.path.append(str(deps_dir))

        spec = importlib.util.find_spec(module_path)
        if spec is None:
            raise ImportError(f"Cannot find module '{module_path}' for plugin '{plugin_name}'")
        if spec.loader is None:
            raise ImportError(f"Cannot load module '{module_path}' for plugin '{plugin_name}'")

        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_path] = mod
        spec.loader.exec_module(mod)

        cls = getattr(mod, class_name, None)
        if cls is None or not (isinstance(cls, type) and issubclass(cls, BasePlugin)):
            raise ValueError(f"'{meta.entry}' is not a valid BasePlugin subclass")
        return cls()
