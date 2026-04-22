import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, cast

from peewee import CharField, DateTimeField, ForeignKeyField, TextField

from waifu.store.models import Conversation, Message


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


class ConversationStore:
    """All conversation/message operations. Inject into CLI and daemon.

    Pass ``conversations_dir`` to enable automatic markdown sync: every time
    a message is added the corresponding ``<title>-<short-id>.md`` file in
    that directory is (re-)written with the full conversation history.
    """

    def __init__(self, conversations_dir: Optional[Path] = None) -> None:
        self._conversations_dir = conversations_dir

    def create(self, title: str) -> Conversation:
        return Conversation.create(title=title)

    def create_with_id(self, id: str, title: str) -> Conversation:
        return Conversation.create(id=id, title=title)

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

    def delete(self, id: str) -> bool:
        n = Conversation.delete().where(Conversation.id == id).execute()
        return n > 0

    def search(self, query: str) -> List[Conversation]:
        matching_ids = Message.select(cast(ForeignKeyField, Message.conversation)).where(
            cast(TextField, Message.content).contains(query)
        )
        return list(
            Conversation.select()
            .where(
                cast(CharField, Conversation.title).contains(query) | cast(CharField, Conversation.id).in_(matching_ids)
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
        msg = Message.create(**kwargs)
        Conversation.update(updated_at=datetime.utcnow()).where(Conversation.id == conversation_id).execute()
        if self._conversations_dir is not None:
            self._sync_markdown(conversation_id)
        return msg

    def add_llm_message(self, conversation_id: str, llm_msg: Dict[str, Any]) -> Message:
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
            text = llm_msg.get("content") or ""
            if text:
                parts.append({"type": "text", "text": text})
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

        return self.add_message(conversation_id, role, parts)

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
                "parts": json.loads(cast(str, m.content)),
            }
            for m in self.get_messages(conversation_id, limit)
        ]

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
