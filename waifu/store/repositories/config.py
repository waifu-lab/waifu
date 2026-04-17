import json
from typing import Any, Optional

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

    def delete(self, key: str) -> None:
        AppConfig.delete().where(AppConfig.key == key).execute()
