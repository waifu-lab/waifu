import uuid
from datetime import datetime
from pathlib import Path

from peewee import (
    BooleanField,
    CharField,
    DateTimeField,
    ForeignKeyField,
    Model,
    SqliteDatabase,
    TextField,
)

# Deferred proxy — models reference this, path set by Database.init()
_db = SqliteDatabase(None)


class BaseModel(Model):
    class Meta:
        database = _db


class Conversation(BaseModel):
    id = CharField(primary_key=True, default=lambda: str(uuid.uuid4()))
    title = CharField()
    created_at = DateTimeField(default=datetime.utcnow)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "conversations"

    def save(self, *args, **kwargs):
        self.updated_at = datetime.utcnow()
        return super().save(*args, **kwargs)


class Message(BaseModel):
    id = CharField(primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation = ForeignKeyField(Conversation, backref="messages", on_delete="CASCADE", column_name="conversation_id")
    role = CharField()  # user | assistant | system | tool
    content = TextField()
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "messages"


class CronJob(BaseModel):
    id = CharField(primary_key=True, default=lambda: str(uuid.uuid4()))
    name = CharField(unique=True)
    type = CharField()  # at | every | cron
    schedule = CharField()
    command = TextField()
    enabled = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "cron_jobs"


class CronRun(BaseModel):
    id = CharField(primary_key=True, default=lambda: str(uuid.uuid4()))
    job = ForeignKeyField(CronJob, backref="runs", on_delete="CASCADE")
    started_at = DateTimeField(default=datetime.utcnow)
    finished_at = DateTimeField(null=True)
    status = CharField()  # running | success | error
    output = TextField(null=True)

    class Meta:
        table_name = "cron_runs"


_TABLES = [Conversation, Message, CronJob, CronRun]


class Database:
    """Injectable wrapper around the peewee SqliteDatabase proxy."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def init(self) -> None:
        """Connect and run migrations (create tables if not exist)."""
        _db.init(
            str(self._path),
            pragmas={
                "journal_mode": "wal",
                "foreign_keys": 1,
            },
        )
        _db.connect(reuse_if_open=True)
        _db.create_tables(_TABLES, safe=True)

    def close(self) -> None:
        if not _db.is_closed():
            _db.close()
