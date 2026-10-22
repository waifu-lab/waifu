import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, cast

from peewee import CharField, DateTimeField, ForeignKeyField, IntegerField, TextField

from waifu.store.models import Conversation, DailyTokenUsage, Message, MessageAttachment, TitleStatus
from waifu_types import Attachment, MessageParts


def _parts_to_text(parts: List[Dict[str, Any]]) -> str:
    """Flatten message parts into plain text for markdown export."""
    lines = []
    for p in parts:
        t = p.get("type", "")
        if t == "text":
            lines.append(p.get("text", ""))
        elif t == "tool-result":
            lines.append(f"> **tool result:** {p.get('result', '')}")
        elif t.startswith("tool-"):
            name = p.get("toolName") or t[5:]
            args = p.get("args", {})
            lines.append(f"> **{name}** `{json.dumps(args, ensure_ascii=False)}`")
    return "\n".join(lines)


def _safe_filename(title: str, id: str) -> str:
    """Build a filesystem-safe filename from title + short id."""
    slug = re.sub(r"[^\w\s-]", "", title).strip()
    slug = re.sub(r"[\s_]+", "-", slug)[:40]
    safe_id = re.sub(r'[<>:"/\\|?*]', "-", id)[:36]
    return f"{slug}-{safe_id}.md" if slug else f"{safe_id}.md"


def _load_parts(raw: str) -> List[Dict[str, Any]]:
    try:
        parts = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return [{"type": "text", "text": raw}]
    return parts if isinstance(parts, list) else [{"type": "text", "text": raw}]


class ConversationStore:
    """All conversation/message operations. Inject into CLI and daemon.

    Pass ``conversations_dir`` to enable automatic markdown sync: every time
    a message is added the corresponding ``<title>-<short-id>.md`` file in
    that directory is (re-)written with the full conversation history.
    """

    def __init__(
        self,
        conversations_dir: Optional[Path] = None,
        attachments_dir: Optional[Path] = None,
    ) -> None:
        self._conversations_dir = conversations_dir
        self._attachments_dir = attachments_dir

    def create(self, title: str) -> Conversation:
        return Conversation.create(title=title)

    def create_with_id(self, id: str, title: str, *, auto_title: bool = False) -> Conversation:

        status = TitleStatus.PENDING if auto_title else TitleStatus.SET
        return Conversation.create(id=id, title=title, title_status=status)

    def needs_auto_title(self, id: str) -> bool:
        return (
            Conversation.select()
            .where((Conversation.id == id) & (Conversation.title_status == TitleStatus.PENDING))
            .exists()
        )

    def set_auto_title(self, id: str, title: str) -> bool:

        n = (
            Conversation.update(title=title, title_status=TitleStatus.SET)
            .where((Conversation.id == id) & (Conversation.title_status == TitleStatus.PENDING))
            .execute()
        )
        return n > 0

    def get(self, id: str) -> Optional[Conversation]:
        return Conversation.get_or_none(Conversation.id == id)

    def resolve(self, id_prefix: str) -> Optional[Conversation]:
        """Return a conversation by exact ID or unique prefix. Returns None if not found or ambiguous."""
        exact = self.get(id_prefix)
        if exact:
            return exact
        matches = list(Conversation.select().where(Conversation.id.startswith(id_prefix)).limit(2))
        return matches[0] if len(matches) == 1 else None

    def list(self, limit: int = 20) -> List[Conversation]:
        q = Conversation.select().order_by(cast(DateTimeField, Conversation.updated_at).desc())
        if limit > 0:
            q = q.limit(limit)
        return list(q)

    def count(self) -> int:
        return Conversation.select().count()

    def update_title(self, id: str, title: str) -> bool:
        """Update the title of a conversation. Returns True if the row existed."""
        n = Conversation.update(title=title, title_status=TitleStatus.SET).where(Conversation.id == id).execute()
        return n > 0

    def delete(self, id: str) -> bool:
        n = Conversation.delete().where(Conversation.id == id).execute()
        if n > 0 and self._attachments_dir is not None:
            shutil.rmtree(self._attachments_dir / id, ignore_errors=True)
        return n > 0

    def search(self, query: str) -> List[Conversation]:
        matching_ids = Message.select(cast(ForeignKeyField, Message.conversation)).where(
            cast(TextField, Message.content).contains(query)
        )
        return list(
            Conversation.select()
            .where(
                cast(CharField, Conversation.id).contains(query)
                | cast(CharField, Conversation.title).contains(query)
                | cast(CharField, Conversation.id).in_(matching_ids)
            )
            .order_by(cast(DateTimeField, Conversation.updated_at).desc())
        )

    # FIXME: 壓縮絕對不是這樣處理的
    def compact(self, id: str) -> int:
        """Delete all but the last system message and last N exchanges.
        Returns number of messages deleted."""
        keep = 20
        total = Message.select().where(Message.conversation == id).count()
        if total <= keep:
            return 0
        cutoff_msg = (
            Message.select()
            .where(cast(ForeignKeyField, Message.conversation) == id)
            .order_by(cast(DateTimeField, Message.created_at).desc())
            .offset(keep)
            .first()
        )
        if cutoff_msg is None:
            return 0
        n = (
            Message.delete()
            .where(
                Message.conversation == id,
                cast(DateTimeField, Message.created_at) <= cast(datetime, cutoff_msg.created_at),
                cast(CharField, Message.role) != "system",
            )
            .execute()
        )
        return n

    def add_message(
        self,
        conversation_id: str,
        role: str,
        parts: Union[List[Dict[str, Any]], str],
        *,
        message_id: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        attachments: Optional[List[Attachment]] = None,
    ) -> Message:
        """Store a message. `parts` may be a list of part objects or a plain string
        (which is wrapped as ``[{"type": "text", "text": parts}]`` automatically)."""
        if isinstance(parts, str):
            parts = [{"type": "text", "text": parts}]
        content = json.dumps(parts, ensure_ascii=False)
        kwargs: Dict[str, Any] = {
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
        }
        if message_id is not None:
            kwargs["id"] = message_id
        if input_tokens is not None:
            kwargs["input_tokens"] = input_tokens
        if output_tokens is not None:
            kwargs["output_tokens"] = output_tokens
        msg = Message.create(**kwargs)
        if attachments:
            try:
                self._save_attachments(cast(str, msg.id), conversation_id, attachments)
            except Exception:
                Message.delete().where(Message.id == msg.id).execute()
                raise
        Conversation.update(updated_at=datetime.utcnow()).where(Conversation.id == conversation_id).execute()
        if (input_tokens or 0) + (output_tokens or 0) > 0:
            self._upsert_daily_tokens(conversation_id, input_tokens or 0, output_tokens or 0)
        if self._conversations_dir is not None:
            self._sync_markdown(conversation_id)
        return msg

    def _save_attachments(
        self,
        message_id: str,
        conversation_id: str,
        attachments: List[Attachment],
    ) -> None:
        """Persist each attachment to disk (if it has bytes) and create a
        MessageAttachment row. Raises on disk error; caller rolls back."""
        for att in attachments:
            att_id = str(uuid.uuid4())
            storage_path: Optional[str] = None
            size = 0
            if att.data:
                if self._attachments_dir is None:
                    raise RuntimeError("attachments_dir not configured")
                ext = os.path.splitext(att.filename)[1]
                rel = Path(conversation_id) / message_id / f"{att_id}{ext}"
                full = self._attachments_dir / rel
                full.parent.mkdir(parents=True, exist_ok=True)
                full.write_bytes(att.data)
                size = len(att.data)
                storage_path = rel.as_posix()
            elif not att.url:
                continue  # no data and no url — nothing to persist
            MessageAttachment.create(
                id=att_id,
                message=message_id,
                conversation_id=conversation_id,
                filename=att.filename,
                content_type=att.content_type,
                size_bytes=size,
                storage_path=storage_path,
                url=att.url,
            )

    def get_attachment(self, attachment_id: str) -> Optional[MessageAttachment]:
        return MessageAttachment.get_or_none(MessageAttachment.id == attachment_id)

    def attachments_for(self, message_id: str) -> List[Dict[str, Any]]:
        rows = list(MessageAttachment.select().where(MessageAttachment.message == message_id))
        result: List[Dict[str, Any]] = []
        for a in rows:
            att_id = cast(str, a.id)
            local_url = f"/attachments/{att_id}" if a.storage_path else None
            result.append(
                {
                    "id": att_id,
                    "filename": cast(str, a.filename),
                    "content_type": cast(str, a.content_type),
                    "size_bytes": cast(int, a.size_bytes),
                    "url": local_url or cast(Optional[str], a.url),
                }
            )
        return result

    def _load_runtime_attachments(self, message_id: str) -> List[Attachment]:
        rows = list(MessageAttachment.select().where(MessageAttachment.message == message_id))
        result: List[Attachment] = []
        for row in rows:
            data = b""
            url = cast(Optional[str], row.url)
            storage_path = cast(Optional[str], row.storage_path)
            if storage_path and self._attachments_dir is not None:
                full = self._attachments_dir / storage_path
                if full.is_file():
                    data = full.read_bytes()
            if not data and not url:
                continue
            result.append(
                Attachment(
                    filename=cast(str, row.filename),
                    content_type=cast(str, row.content_type),
                    data=data,
                    url=url,
                )
            )
        return result

    def _upsert_daily_tokens(self, conversation_id: str, input_tokens: int, output_tokens: int) -> None:
        """Upsert 當日 token 彙總（per-conversation + 全域）"""
        today = datetime.now(timezone.utc).date()
        total = input_tokens + output_tokens

        for cid in (conversation_id, None):
            existing = (
                DailyTokenUsage.select()
                .where(
                    DailyTokenUsage.date == today,
                    DailyTokenUsage.conversation_id == cid,
                )
                .first()
            )
            if existing is not None:
                DailyTokenUsage.update(
                    input_tokens=cast(IntegerField, DailyTokenUsage.input_tokens) + input_tokens,
                    output_tokens=cast(IntegerField, DailyTokenUsage.output_tokens) + output_tokens,
                    total_tokens=cast(IntegerField, DailyTokenUsage.total_tokens) + total,
                    updated_at=datetime.utcnow(),
                ).where(
                    DailyTokenUsage.date == today,
                    DailyTokenUsage.conversation_id == cid,
                ).execute()
            else:
                DailyTokenUsage.create(
                    date=today,
                    conversation_id=cid,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total,
                )

    def add_llm_message(
        self,
        conversation_id: str,
        llm_msg: Dict[str, Any],
        *,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        attachments: Optional[List[Attachment]] = None,
    ) -> Message:
        """Convert a shuvi/LLM-format message dict and persist it.

        Handles:
        - user/system:  {"role": "user", "content": "text"}
        - assistant:    {"role": "assistant", "content": "...", "tool_calls": [...]}
        - tool result:  {"role": "tool", "tool_call_id": "...", "content": "..."}
        """
        role = llm_msg.get("role", "assistant")
        parts: List[Dict[str, Any]] = []

        if role == "tool":
            parts.append(
                {
                    "type": "tool-result",
                    "toolCallId": llm_msg.get("tool_call_id", ""),
                    "result": llm_msg.get("content", ""),
                }
            )
        else:
            raw = llm_msg.get("content") or ""
            if isinstance(raw, list):
                # multimodal parts — extract text parts, ignore image_url etc.
                for p in raw:
                    if isinstance(p, dict) and p.get("type") == "text":
                        parts.append({"type": "text", "text": p.get("text", "")})
            elif raw:
                parts.append({"type": "text", "text": raw})
            for tc in llm_msg.get("tool_calls", []):
                fn = tc.get("function", {})
                raw_args = fn.get("arguments", "{}")
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except json.JSONDecodeError:
                    args = {"_raw": raw_args}
                parts.append(
                    {
                        "type": f"tool-{fn.get('name', 'unknown')}",
                        "toolCallId": tc.get("id", ""),
                        "toolName": fn.get("name", ""),
                        "args": args,
                    }
                )

        return self.add_message(
            conversation_id,
            role,
            parts,
            input_tokens=input_tokens if role == "assistant" else None,
            output_tokens=output_tokens if role == "assistant" else None,
            attachments=attachments,
        )

    def get_messages(self, conversation_id: str, limit: int = 100) -> List[Message]:
        q = (
            Message.select()
            .where(cast(ForeignKeyField, Message.conversation) == conversation_id)
            .order_by(cast(DateTimeField, Message.created_at).asc())
        )
        if limit > 0:
            q = q.limit(limit)
        return list(q)

    def get_messages_as_dicts(self, conversation_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        return [
            {
                "id": cast(str, m.id),
                "role": cast(str, m.role),
                "parts": _load_parts(cast(str, m.content)),
                "attachments": self.attachments_for(cast(str, m.id)),
            }
            for m in self.get_messages(conversation_id, limit)
        ]

    def get_llm_messages(self, conversation_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for msg in self.get_messages(conversation_id, limit):
            parts = _load_parts(cast(str, msg.content))
            role = cast(str, msg.role)
            text_parts = [str(p.get("text", "")) for p in parts if p.get("type") == "text" and p.get("text")]
            text = "\n".join(text_parts)

            if role == "tool":
                tool_result = next((p for p in parts if p.get("type") == "tool-result"), None)
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_result.get("toolCallId", "") if tool_result else "",
                        "content": tool_result.get("result", "") if tool_result else text,
                    }
                )
                continue

            if role == "assistant":
                tool_calls = []
                for part in parts:
                    part_type = str(part.get("type", ""))
                    if not part_type.startswith("tool-"):
                        continue
                    args = part.get("args", {})
                    tool_calls.append(
                        {
                            "id": part.get("toolCallId", ""),
                            "type": "function",
                            "function": {
                                "name": part.get("toolName") or part_type[5:],
                                "arguments": args if isinstance(args, str) else json.dumps(args, ensure_ascii=False),
                            },
                        }
                    )
                payload: Dict[str, Any] = {"role": "assistant", "content": text or None}
                if tool_calls:
                    payload["tool_calls"] = tool_calls
                result.append(payload)
                continue

            if role == "user":
                attachments = self._load_runtime_attachments(cast(str, msg.id))
                content = MessageParts(content=text, attachments=attachments).to_user_message().content
                result.append({"role": "user", "content": content})
                continue

            result.append({"role": role, "content": text})
        return result

    def export_markdown(self, conversation_id: str, dest: Path) -> Path:
        """Write (or overwrite) a markdown file for the conversation.

        Returns the path that was written.
        """
        conv = self.get(conversation_id)
        if conv is None:
            raise ValueError(f"Conversation not found: {conversation_id}")

        msgs = self.get_messages(conversation_id, limit=0)  # 0 → fetch all

        lines: List[str] = [
            f"# {cast(str, conv.title)}",
            "",
            f"**ID:** {cast(str, conv.id)}  ",
            f"**Created:** {str(cast(datetime, conv.created_at))[:16]}  ",
            f"**Updated:** {str(cast(datetime, conv.updated_at))[:16]}",
            "",
            "---",
            "",
        ]

        role_labels = {
            "user": "**User**",
            "assistant": "**Assistant**",
            "system": "**System**",
            "tool": "**Tool**",
        }

        for m in msgs:
            role = cast(str, m.role)
            label = role_labels.get(role, f"**{role}**")
            ts = str(cast(datetime, m.created_at))[:16]
            try:
                parts = json.loads(cast(str, m.content))
            except (json.JSONDecodeError, TypeError):
                parts = [{"type": "text", "text": cast(str, m.content)}]
            body = _parts_to_text(parts)
            lines += [f"{label} · {ts}", "", body, "", "---", ""]

        dest.write_text("\n".join(lines), encoding="utf-8")
        return dest

    def _sync_markdown(self, conversation_id: str) -> None:
        """Re-export markdown for a conversation into ``self._conversations_dir``."""
        if self._conversations_dir is None:
            return
        conv = self.get(conversation_id)
        if conv is None:
            return
        filename = _safe_filename(cast(str, conv.title), cast(str, conv.id))
        self.export_markdown(conversation_id, self._conversations_dir / filename)
