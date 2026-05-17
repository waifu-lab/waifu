import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

from croniter import croniter

from waifu.logger import logger

if TYPE_CHECKING:
    from waifu.cron.executor import CronExecutor
    from waifu.store.cron import CronStore
    from waifu.store.models import CronJob


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _compute_next_run(job: "CronJob", after: datetime) -> Optional[datetime]:
    job_type = str(job.type)
    schedule = str(job.schedule)

    if job_type == "at":
        try:
            t = datetime.fromisoformat(schedule)
            return t if t > after else None
        except ValueError:
            logger.warning("CronJob {!r}: invalid 'at' schedule {!r}", job.name, schedule)
            return None

    if job_type == "every":
        interval = _parse_interval(schedule)
        if interval is None:
            logger.warning("CronJob {!r}: invalid 'every' schedule {!r}", job.name, schedule)
            return None
        return after + interval

    if job_type == "cron":
        try:
            return croniter(schedule, after).get_next(datetime)
        except Exception:
            logger.warning("CronJob {!r}: invalid cron expression {!r}", job.name, schedule)
            return None

    logger.warning("CronJob {!r}: unknown type {!r}", job.name, job_type)
    return None


def _parse_interval(s: str) -> Optional[timedelta]:
    """解析 '30s' / '5m' / '2h' / '1d' / '1h30m' / '2d4h' → timedelta。"""
    s = s.strip().lower()
    if not s:
        return None

    matches = list(re.finditer(r"(\d+)([smhd])", s))
    if not matches:
        return None

    if "".join(m.group(0) for m in matches) != s:
        return None

    total = timedelta()
    for m in matches:
        value = int(m.group(1))
        unit = m.group(2)

        if unit == "s":
            total += timedelta(seconds=value)
        elif unit == "m":
            total += timedelta(minutes=value)
        elif unit == "h":
            total += timedelta(hours=value)
        elif unit == "d":
            total += timedelta(days=value)

    return total


class CronScheduler:
    def __init__(self, store: "CronStore", executor: "CronExecutor") -> None:
        self._store = store
        self._executor = executor
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="cron-scheduler")
        logger.info("CronScheduler started")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("CronScheduler stopped")

    async def _loop(self) -> None:
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("CronScheduler tick error, retrying in 60s")
                await asyncio.sleep(60)

    async def _tick(self) -> None:
        jobs = self._store.list_enabled()
        if not jobs:
            await asyncio.sleep(60)
            return

        now = _now()
        upcoming: list[tuple[datetime, "CronJob"]] = []
        for job in jobs:
            t = _compute_next_run(job, now)
            if t is not None:
                upcoming.append((t, job))

        if not upcoming:
            await asyncio.sleep(60)
            return

        upcoming.sort(key=lambda x: x[0])
        next_time, _ = upcoming[0]
        sleep_secs = max(0.0, (next_time - _now()).total_seconds())

        if sleep_secs > 0:
            await asyncio.sleep(sleep_secs)

        fire_time = _now()
        for t, job in upcoming:
            if (t - fire_time).total_seconds() <= 1:
                asyncio.create_task(self._run_job(job), name=f"cron-job-{job.name}")

    async def _run_job(self, job: "CronJob") -> None:
        run = self._store.start_run(str(job.id))
        logger.info("CronJob {!r} started (kind={})", job.name, job.kind)
        try:
            output = await self._executor.execute(job)
            self._store.finish_run(str(run.id), status="success", output=output)
            logger.info("CronJob {!r} finished successfully", job.name)

            if str(job.type) == "at":
                self._store.disable(str(job.id))
        except Exception:
            logger.exception("CronJob {!r} failed", job.name)
            self._store.finish_run(str(run.id), status="error", output="see server log")
