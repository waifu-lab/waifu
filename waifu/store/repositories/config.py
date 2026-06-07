import json
from typing import Any, Optional, cast

from waifu.store.models import AppConfig


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
        return {r.key: json.loads(r.value) for r in AppConfig.select()}

    def upsert_all(self, entries: dict) -> None:
        """Write entries into DB, overwriting existing keys."""
        for key, value in entries.items():
            AppConfig.insert(key=key, value=json.dumps(value)).on_conflict(
                conflict_target=[AppConfig.key],
                update={AppConfig.value: json.dumps(value)},
            ).execute()

    def replace_all(self, entries: dict) -> None:
        """Replace the stored config snapshot so DB matches the config file."""
        db = cast(Any, AppConfig)._meta.database
        with db.atomic():
            if entries:
                AppConfig.delete().where(AppConfig.key.not_in(list(entries))).execute()
            else:
                AppConfig.delete().execute()
            self.upsert_all(entries)

    def seed_if_absent(self, entries: dict) -> None:
        for key, value in entries.items():
            AppConfig.insert(key=key, value=json.dumps(value)).on_conflict_ignore().execute()

    def delete(self, key: str) -> None:
        AppConfig.delete().where(AppConfig.key == key).execute()
