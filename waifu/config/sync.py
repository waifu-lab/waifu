import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import tomlkit
from pydantic import ValidationError

from waifu.config import WaifuConfig
from waifu.logger import logger

if TYPE_CHECKING:
    from waifu.store.repositories.config import AppConfigRepository

SNAPSHOT_KEY = "__config_toml_snapshot__"


class ConfigError(ValueError): ...


def flatten(data: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:

    entries: Dict[str, Any] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict) and value:
            entries.update(flatten(value, path))
        else:
            entries[path] = value
    return entries


def unflatten(entries: Dict[str, Any]) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    for path, value in entries.items():
        cur = data
        *parents, leaf = path.split(".")
        for key in parents:
            nxt = cur.get(key)
            if not isinstance(nxt, dict):
                nxt = cur[key] = {}
            cur = nxt
        cur[leaf] = value
    return data


def _without_prefix(entries: Dict[str, Any], key: str) -> Dict[str, Any]:
    return {k: v for k, v in entries.items() if k != key and not k.startswith(f"{key}.")}


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


class ConfigSync:
    def __init__(self, repo: "AppConfigRepository", toml_path: Path) -> None:
        self._repo = repo
        self._path = toml_path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> WaifuConfig:
        """同步後回傳目前生效的設定"""
        return self.sync()

    def sync(self) -> WaifuConfig:
        entries = self._current_entries()
        if not entries:
            raise ConfigError(f"No config found in DB or {self._path}; run `waifu init` first")
        return self._commit(entries)

    def set(self, key: str, value: Any) -> WaifuConfig:

        entries = _without_prefix(self._current_entries(), key)
        if isinstance(value, dict):
            entries.update(flatten(value, key))
        elif value is not None:
            entries[key] = value
        return self._commit(entries)

    def adopt(self, config: WaifuConfig) -> None:

        self._repo.replace_all(flatten(config.model_dump(exclude_none=True)))

    def _current_entries(self) -> Dict[str, Any]:

        entries = self._repo.get_all()
        file_entries = self._read_file()
        return entries if file_entries is None else self._merge_user_edits(entries, file_entries)

    def _merge_user_edits(self, entries: Dict[str, Any], file_entries: Dict[str, Any]) -> Dict[str, Any]:
        snapshot: Optional[Dict[str, Any]] = self._repo.get(SNAPSHOT_KEY)
        if snapshot is None:
            # 從未同步過（新安裝或從舊版升級）：以 config.toml 為準
            return dict(file_entries)
        merged = dict(entries)
        for key, value in file_entries.items():
            if key not in snapshot or not _same(snapshot[key], value):
                merged = _without_prefix(merged, key)
                merged[key] = value
        for key in snapshot:
            if key not in file_entries:
                merged.pop(key, None)
        return merged

    def _commit(self, entries: Dict[str, Any]) -> WaifuConfig:
        try:
            config = WaifuConfig.model_validate(unflatten(entries))
        except ValidationError as exc:
            raise ConfigError(str(exc)) from exc

        normalized = flatten(config.model_dump(exclude_none=True))
        dropped = sorted(
            k for k in entries if k not in normalized and not any(n.startswith(f"{k}.") for n in normalized)
        )
        if dropped:
            logger.warning("Ignoring unknown config keys: {}", ", ".join(dropped))

        self._repo.replace_all(normalized)
        self._write_file(unflatten(normalized))
        self._repo.set(SNAPSHOT_KEY, normalized)
        return config

    def _read_file(self) -> Optional[Dict[str, Any]]:
        if not self._path.exists():
            return None
        return flatten(tomlkit.parse(self._path.read_text(encoding="utf-8")).unwrap())

    def _write_file(self, data: Dict[str, Any]) -> None:
        # 以 bytes 讀取：read_text 會把 \r\n 轉成 \n，無法得知原檔換行
        original = self._path.read_bytes().decode("utf-8") if self._path.exists() else ""
        doc = tomlkit.parse(original) if original else tomlkit.document()
        _merge_into(doc, data)
        text = tomlkit.dumps(doc).replace("\r\n", "\n")
        if text == original.replace("\r\n", "\n"):
            return
        newline = "\r\n" if "\r\n" in original else None  # 沿用原檔換行，新檔依平台
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8", newline=newline) as f:
            f.write(text)


def _merge_into(table: Any, data: Dict[str, Any]) -> None:

    for key in [k for k in table if k not in data]:
        del table[key]
    for key, value in data.items():
        if isinstance(value, dict):
            if key not in table or not isinstance(table[key], dict):
                table[key] = tomlkit.table()
            _merge_into(table[key], value)
        elif key not in table or not _same(_plain(table[key]), value):
            table[key] = value


def _plain(item: Any) -> Any:
    return item.unwrap() if hasattr(item, "unwrap") else item


__all__: List[str] = ["ConfigError", "ConfigSync", "SNAPSHOT_KEY", "flatten", "unflatten"]
