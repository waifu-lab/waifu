from datetime import datetime
from typing import List, Optional, cast

from peewee import BooleanField, DateTimeField, ForeignKeyField

from waifu.store.models import CronJob, CronRun


class CronStore:
    """All cron job operations. Inject into CLI and scheduler."""

    def create(
        self,
        name: str,
        type: str,
        schedule: str,
        command: str,
        kind: str = "shell",
        target_conversation_id: Optional[str] = None,
        sender_user_id: Optional[str] = None,
        sender_display_name: Optional[str] = None,
    ) -> CronJob:
        return CronJob.create(
            name=name,
            type=type,
            schedule=schedule,
            command=command,
            kind=kind,
            target_conversation_id=target_conversation_id,
            sender_user_id=sender_user_id,
            sender_display_name=sender_display_name,
        )

    def get(self, id: str) -> Optional[CronJob]:
        return CronJob.get_or_none(CronJob.id == id)

    def get_by_name(self, name: str) -> Optional[CronJob]:
        return CronJob.get_or_none(CronJob.name == name)

    def list(self) -> List[CronJob]:
        return list(CronJob.select().order_by(cast(DateTimeField, CronJob.created_at).asc()))

    def list_enabled(self) -> List[CronJob]:
        return list(
            CronJob.select()
            .where(cast(BooleanField, CronJob.enabled) == True)
            .order_by(cast(DateTimeField, CronJob.created_at).asc())
        )

    def enable(self, id: str) -> bool:
        n = CronJob.update(enabled=True).where(CronJob.id == id).execute()
        return n > 0

    def disable(self, id: str) -> bool:
        n = CronJob.update(enabled=False).where(CronJob.id == id).execute()
        return n > 0

    def remove(self, id: str) -> bool:
        n = CronJob.delete().where(CronJob.id == id).execute()
        return n > 0

    def start_run(self, job_id: str) -> CronRun:
        return CronRun.create(job_id=job_id, status="running")

    def finish_run(self, run_id: str, status: str, output: Optional[str] = None) -> None:
        CronRun.update(
            finished_at=datetime.utcnow(),
            status=status,
            output=output,
        ).where(CronRun.id == run_id).execute()

    def history(self, job_id: str, limit: int = 20) -> List[CronRun]:
        return list(
            CronRun.select()
            .where(cast(ForeignKeyField, CronRun.job) == job_id)
            .order_by(cast(DateTimeField, CronRun.started_at).desc())
            .limit(limit)
        )
