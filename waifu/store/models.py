import uuid
from datetime import datetime
from pathlib import Path

from peewee import (
    BooleanField,
    CharField,
    DateField,
    DateTimeField,
    ForeignKeyField,
    IntegerField,
    Model,
    SqliteDatabase,
    TextField,
)

# Deferred proxy — models reference this, path set by Database.init()
_db = SqliteDatabase(None)


class BaseModel(Model):
    class Meta:
        database = _db


# FIXME: 解決reportAssignmentType
# TODO: 重新思索表的設計


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
    conversation = ForeignKeyField(
        Conversation, backref="messages", on_delete="CASCADE", column_name="conversation_id"
    )
    role = CharField()  # user | assistant | system | tool
    content = TextField()
    input_tokens = IntegerField(null=True)   # assistant 訊息的 LLM input token 數
    output_tokens = IntegerField(null=True)  # assistant 訊息的 LLM output token 數
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "messages"


class MessageAttachment(BaseModel):
    id = CharField(primary_key=True, default=lambda: str(uuid.uuid4()))
    message = ForeignKeyField(
        Message, backref="attachments", on_delete="CASCADE", column_name="message_id"
    )
    conversation_id = CharField()  # 冗餘欄位，方便依 conversation 整批清檔
    filename = CharField()
    content_type = CharField()
    size_bytes = IntegerField(default=0)
    storage_path = CharField(null=True)  # 相對 attachments_dir 的路徑；與 url 至少一個
    url = CharField(null=True)           # 遠端 CDN（Discord/Telegram）；與 storage_path 至少一個
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "message_attachments"


class DailyTokenUsage(BaseModel):
    """每日 token 使用量彙總（UTC date）"""

    id = CharField(primary_key=True, default=lambda: str(uuid.uuid4()))
    date = DateField()                        # UTC date, e.g. 2026-04-23
    conversation_id = CharField(null=True)    # None = 全域彙總
    input_tokens = IntegerField(default=0)
    output_tokens = IntegerField(default=0)
    total_tokens = IntegerField(default=0)
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "daily_token_usage"
        indexes = ((("date", "conversation_id"), True),)  # unique together


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


class PluginConfig(BaseModel):
    id = CharField(primary_key=True, default=lambda: str(uuid.uuid4()))
    name = CharField(unique=True)  # 來自 metadata.json["name"]
    plugin_name = CharField()  # plugins_dir 下的資料夾名稱
    enabled = BooleanField(default=True)
    config_json = TextField(default="{}")  # JSON dict，傳給 on_load
    installed_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "plugin_configs"


class MCPServer(BaseModel):
    id = CharField(primary_key=True, default=lambda: str(uuid.uuid4()))
    name = CharField(unique=True)
    type = CharField()  # "stdio" | "sse"
    command = TextField(null=True)  # stdio: JSON array, e.g. '["npx","mcp-fs"]'
    url = CharField(null=True)  # sse: http://...
    enabled = BooleanField(default=True)
    config_json = TextField(default="{}")

    class Meta:
        table_name = "mcp_servers"


class AppConfig(BaseModel):
    key = CharField(primary_key=True)  # e.g. "provider.model"
    value = TextField()  # JSON-encoded value
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "app_config"

    def save(self, *args, **kwargs):
        self.updated_at = datetime.utcnow()
        return super().save(*args, **kwargs)


class Character(BaseModel):
    id = CharField(primary_key=True, default=lambda: str(uuid.uuid4()))
    name = CharField(unique=True)
    soul_path = CharField()  # 絕對路徑，指向 soul.md
    avatar_path = CharField(null=True)  # 絕對路徑，指向 avatar 圖檔
    live2d_dir = CharField(null=True)  # 絕對路徑，指向 live2d/ 資料夾
    active = BooleanField(default=False)  # 同時只有一個 active
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "characters"


class Relationship(BaseModel):
    id = CharField(primary_key=True, default=lambda: str(uuid.uuid4()))
    character = ForeignKeyField(
        Character, backref="relationships", on_delete="CASCADE", column_name="character_id"
    )
    user_id = CharField()  # e.g. "discord:user:123456"
    display_name = CharField()
    notes = TextField(default="")  # markdown 格式，記住的事
    memory_path = CharField(null=True)  # 指向 ~/.waifu/memory/{char}/direct/{user_id}.md
    updated_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "relationships"
        indexes = ((("character_id", "user_id"), True),)  # unique together

    def save(self, *args, **kwargs):
        self.updated_at = datetime.utcnow()
        return super().save(*args, **kwargs)


_TABLES = [Conversation, Message, MessageAttachment, DailyTokenUsage, CronJob, CronRun, PluginConfig, MCPServer, AppConfig, Character, Relationship]


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
