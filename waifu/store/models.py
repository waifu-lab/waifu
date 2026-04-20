import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

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

#FIXME: 解決reportAssignmentType
#TODO: 重新思索表的設計

class Conversation(BaseModel):
    id: str = CharField(primary_key=True, default=lambda: str(uuid.uuid4()))
    title: str = CharField()
    created_at: datetime = DateTimeField(default=datetime.utcnow)
    updated_at: datetime = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "conversations"

    def save(self, *args, **kwargs):
        self.updated_at = datetime.utcnow()
        return super().save(*args, **kwargs)


class Message(BaseModel):
    id: str = CharField(primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation: Conversation = ForeignKeyField(
        Conversation, backref="messages", on_delete="CASCADE", column_name="conversation_id"
    )
    conversation_id: str  # raw FK value, auto-maintained by Peewee
    role: str = CharField()  # user | assistant | system | tool
    content: str = TextField()
    created_at: datetime = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "messages"


class CronJob(BaseModel):
    id: str = CharField(primary_key=True, default=lambda: str(uuid.uuid4()))
    name: str = CharField(unique=True)
    type: str = CharField()  # at | every | cron
    schedule: str = CharField()
    command: str = TextField()
    enabled: bool = BooleanField(default=True)
    created_at: datetime = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "cron_jobs"


class CronRun(BaseModel):
    id: str = CharField(primary_key=True, default=lambda: str(uuid.uuid4()))
    job: CronJob = ForeignKeyField(CronJob, backref="runs", on_delete="CASCADE")
    job_id: str  # raw FK value, auto-maintained by Peewee
    started_at: datetime = DateTimeField(default=datetime.utcnow)
    finished_at: Optional[datetime] = DateTimeField(null=True)
    status: str = CharField()  # running | success | error
    output: Optional[str] = TextField(null=True)

    class Meta:
        table_name = "cron_runs"


class PluginConfig(BaseModel):
    id: str = CharField(primary_key=True, default=lambda: str(uuid.uuid4()))
    name: str = CharField(unique=True)  # 來自 metadata.json["name"]
    plugin_name: str = CharField()  # plugins_dir 下的資料夾名稱
    enabled: bool = BooleanField(default=True)
    config_json: str = TextField(default="{}")  # JSON dict，傳給 on_load
    installed_at: datetime = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "plugin_configs"


class MCPServer(BaseModel):
    id: str = CharField(primary_key=True, default=lambda: str(uuid.uuid4()))
    name: str = CharField(unique=True)
    type: str = CharField()  # "stdio" | "sse"
    command: Optional[str] = TextField(null=True)  # stdio: JSON array, e.g. '["npx","mcp-fs"]'
    url: Optional[str] = CharField(null=True)  # sse: http://...
    enabled: bool = BooleanField(default=True)
    config_json: str = TextField(default="{}")

    class Meta:
        table_name = "mcp_servers"


class AppConfig(BaseModel):
    key: str = CharField(primary_key=True)  # e.g. "provider.model"
    value: str = TextField()  # JSON-encoded value
    updated_at: datetime = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "app_config"

    def save(self, *args, **kwargs):
        self.updated_at = datetime.utcnow()
        return super().save(*args, **kwargs)


class Character(BaseModel):
    id: str = CharField(primary_key=True, default=lambda: str(uuid.uuid4()))
    name: str = CharField(unique=True)
    soul_path: str = CharField()  # 絕對路徑，指向 soul.md
    avatar_path: Optional[str] = CharField(null=True)  # 絕對路徑，指向 avatar 圖檔
    live2d_dir: Optional[str] = CharField(null=True)  # 絕對路徑，指向 live2d/ 資料夾
    active: bool = BooleanField(default=False)  # 同時只有一個 active
    created_at: datetime = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "characters"


class Relationship(BaseModel):
    id: str = CharField(primary_key=True, default=lambda: str(uuid.uuid4()))
    character: Character = ForeignKeyField(
        Character, backref="relationships", on_delete="CASCADE", column_name="character_id"
    )
    character_id: str  # raw FK value, auto-maintained by Peewee
    user_id: str = CharField()  # e.g. "discord:user:123456"
    display_name: str = CharField()
    notes: str = TextField(default="")  # markdown 格式，記住的事
    memory_path: Optional[str] = CharField(null=True)  # 指向 ~/.waifu/memory/{char}/direct/{user_id}.md
    updated_at: datetime = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "relationships"
        indexes = ((("character_id", "user_id"), True),)  # unique together

    def save(self, *args, **kwargs):
        self.updated_at = datetime.utcnow()
        return super().save(*args, **kwargs)


_TABLES = [Conversation, Message, CronJob, CronRun, PluginConfig, MCPServer, AppConfig, Character, Relationship]


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
