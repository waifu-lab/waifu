import json
from typing import Any, cast

from waifu.store.models import AppConfig

RESERVED_PREFIX = "__"


class AppConfigRepository:
    def set(self, key: str, value: Any) -> None:
        AppConfig.insert(key=key, value=json.dumps(value)).on_conflict(
            conflict_target=[AppConfig.key],
            update={AppConfig.value: json.dumps(value)},
        ).execute()

    def get(self, key: str, default: Any = None) -> Any:
        row = AppConfig.get_or_none(AppConfig.key == key)
        return json.loads(row.value) if row else default

    def get_all(self) -> dict:
        return {r.key: json.loads(r.value) for r in AppConfig.select() if not str(r.key).startswith(RESERVED_PREFIX)}

    def upsert_all(self, entries: dict) -> None:
        """Write entries into DB, overwriting existing keys."""
        for key, value in entries.items():
            AppConfig.insert(key=key, value=json.dumps(value)).on_conflict(
                conflict_target=[AppConfig.key],
                update={AppConfig.value: json.dumps(value)},
            ).execute()

    def replace_all(self, entries: dict) -> None:
        """讓 DB 內的設定（保留 key 除外）完全等於 entries"""
        db = cast(Any, AppConfig)._meta.database
        with db.atomic():
            stale = [k for k in self.get_all() if k not in entries]
            if stale:
                AppConfig.delete().where(AppConfig.key.in_(stale)).execute()
            self.upsert_all(entries)

    def seed_if_absent(self, entries: dict) -> None:
        for key, value in entries.items():
            AppConfig.insert(key=key, value=json.dumps(value)).on_conflict_ignore().execute()

    def delete(self, key: str) -> None:
        AppConfig.delete().where(AppConfig.key == key).execute()
