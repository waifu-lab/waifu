import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from waifu_types import AssistantMessage, BaseMessage, GenericMessage, SystemMessage, ToolMessage, UserMessage

_SUMMARY_MARKER = "[memory_summary]"


def _dict_to_message(d: Dict[str, Any]) -> BaseMessage:
    role = d.get("role", "")
    if role == "user":
        return UserMessage(content=d.get("content", ""))
    if role == "assistant":
        return AssistantMessage(content=d.get("content"), tool_calls=d.get("tool_calls"))
    if role == "tool":
        return ToolMessage(tool_call_id=d.get("tool_call_id", ""), content=d.get("content", ""))
    if role == "system":
        return SystemMessage(content=d.get("content", ""))
    return GenericMessage(**d)


_SECTION_RE = re.compile(r"^## (.+)$", re.MULTILINE)
_MSG_RE = re.compile(
    r"\*\*(\w+)\*\* · (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\n(.*?)(?=\n\*\*\w+\*\* ·|\Z)",
    re.DOTALL,
)


@dataclass
class MemoryFile:
    """記憶檔案的結構化表示"""

    header: str = ""
    relationship: str = ""
    facts: str = ""
    recent_messages: List[Dict[str, Any]] = field(default_factory=list)
    summary: str = ""


def _sanitize_filename(key: str) -> str:
    """將 conversation_id 轉換為安全的檔案名稱"""
    return key.replace(":", "_").replace("/", "_").replace("\\", "_")


def _messages_to_text(messages: List[Dict[str, Any]]) -> str:
    """將訊息列表轉為可讀文字（用於摘要層）"""
    lines: List[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        lines.append(f"[{role}] {content}")
    return "\n".join(lines)


def _format_message_md(role: str, content: str) -> str:
    """將單則訊息格式化為 markdown"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"**{role}** · {ts}\n{content}"


def _split_sections(lines: List[str]) -> Dict[str, str]:
    """依 ## 標題切分 markdown 區塊"""
    sections: Dict[str, str] = {}
    current_section: Optional[str] = None
    current_lines: List[str] = []

    for line in lines:
        match = _SECTION_RE.match(line)
        if match:
            if current_section is not None:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = match.group(1).strip()
            current_lines = []
        elif current_section is not None:
            if line.strip() != "---":
                current_lines.append(line)

    if current_section is not None:
        sections[current_section] = "\n".join(current_lines).strip()
    return sections


def _parse_recent_messages(sections: Dict[str, str]) -> List[Dict[str, Any]]:
    """從 sections 中解析近期對話訊息"""
    recent_key = next((k for k in sections if k.startswith("近期對話")), None)
    if not recent_key or not sections[recent_key]:
        return []
    messages: List[Dict[str, Any]] = []
    for m in _MSG_RE.finditer(sections[recent_key]):
        role = m.group(1).strip()
        content = m.group(3).strip()
        if content:
            messages.append({"role": role, "content": content})
    return messages


def _parse_memory_file(text: str) -> MemoryFile:
    """將 markdown 文字解析為 MemoryFile 結構"""
    mem = MemoryFile()

    lines = text.split("\n")
    if lines and lines[0].startswith("# "):
        mem.header = lines[0]

    sections = _split_sections(lines)
    mem.relationship = sections.get("關係", "")
    mem.facts = sections.get("記住的事", "")
    mem.summary = sections.get("舊對話摘要", "")
    mem.recent_messages = _parse_recent_messages(sections)

    return mem


def _render_memory_file(mem: MemoryFile, max_recent: int = 20) -> str:
    """將 MemoryFile 結構序列化為 markdown 文字"""
    parts: List[str] = []

    # Header
    parts.append(mem.header or "# Memory")
    parts.append("")

    # 關係
    parts.append("## 關係")
    if mem.relationship:
        parts.append(mem.relationship)
    parts.append("")

    # 記住的事
    parts.append("## 記住的事")
    if mem.facts:
        parts.append(mem.facts)
    parts.append("")
    parts.append("---")
    parts.append("")

    # 近期對話
    parts.append(f"## 近期對話（最近 {max_recent} 則）")
    parts.append("")
    for msg in mem.recent_messages:
        parts.append(_format_message_md(msg["role"], msg.get("content", "")))
        parts.append("")

    # 舊對話摘要
    parts.append("## 舊對話摘要")
    parts.append("")
    if mem.summary:
        parts.append(mem.summary)
        parts.append("")

    return "\n".join(parts)


class FileMemoryStore:
    """
    ```
    memory/
        ├── {character_name}/
        │   ├── direct/
        │   │   └── {source}_dm_{user_id}.md
        │   └── groups/
        │       └── {source}_{room_id}.md
        └── _sessions/
            └── ws_{token}.md
    ```
    ```
    # Memory: {display_name} ({user_id})
    ## 關係
    ...
    ## 記住的事
    ...
    ---
    ## 近期對話
    [verbatim messages]
    ## 舊對話摘要
    [compressed text]
    ```
    """

    def __init__(
        self,
        memory_dir: Path,
        character_name: Optional[str] = None,
        max_recent: int = 20,
        share_direct_memories: bool = True,
    ) -> None:
        self._memory_dir = memory_dir
        self._character = character_name
        self._max_recent = max_recent
        self._share_direct_memories = share_direct_memories

    async def load(self, key: str) -> List[BaseMessage]:
        """回傳：舊對話摘要 system message + 近期原文"""
        path = self._resolve_path(key)
        if not path.exists():
            return []

        mem = _parse_memory_file(path.read_text(encoding="utf-8"))
        result: List[Dict[str, Any]] = []

        if mem.summary:
            result.append(
                {
                    "role": "system",
                    "content": f"{_SUMMARY_MARKER}\n以下是過去的對話摘要：\n{mem.summary}",
                }
            )

        result.extend(mem.recent_messages)
        return [_dict_to_message(d) for d in result]

    async def save(self, key: str, messages: List[BaseMessage]) -> None:
        """
        1. 過濾掉摘要 system message
        2. 超過 max_recent 的舊訊息壓入摘要層
        3. 保留 relationship / facts 不動
        """
        path = self._resolve_path(key)

        if path.exists():
            mem = _parse_memory_file(path.read_text(encoding="utf-8"))
        else:
            mem = MemoryFile(header=f"# Memory: {key}")
            mem.relationship = f"- 親密度: 0\n- 初次見面: {datetime.now().strftime('%Y-%m-%d')}"

        raw = [m.model_dump(exclude_none=True) for m in messages]
        actual_messages = [
            m
            for m in raw
            if not (
                m.get("role") == "system"
                and isinstance(m.get("content", ""), str)
                and m["content"].startswith(_SUMMARY_MARKER)
            )
        ]

        # 雙層記憶：超過上限的舊訊息壓入摘要
        if len(actual_messages) > self._max_recent:
            overflow = actual_messages[: len(actual_messages) - self._max_recent]
            overflow_text = _messages_to_text(overflow)
            if mem.summary:
                mem.summary = mem.summary + "\n\n" + overflow_text
            else:
                mem.summary = overflow_text
            mem.recent_messages = actual_messages[-self._max_recent :]
        else:
            mem.recent_messages = list(actual_messages)

        # 寫回檔案
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            _render_memory_file(mem, self._max_recent),
            encoding="utf-8",
        )

    async def clear(self, key: str) -> None:
        """清除短期對話與摘要，保留關係與記住的事。"""
        path = self._resolve_path(key)
        if not path.exists():
            return
        mem = _parse_memory_file(path.read_text(encoding="utf-8"))
        mem.recent_messages = []
        mem.summary = ""
        path.write_text(
            _render_memory_file(mem, self._max_recent),
            encoding="utf-8",
        )

    async def get_relationship(self, key: str) -> str:
        """
        取得指定對話的關係層文字

        用於 GROUP 模式時，傳入使用者的 direct key 以取得個人關係
        """
        path = self._resolve_path(key)
        if not path.exists():
            return ""
        mem = _parse_memory_file(path.read_text(encoding="utf-8"))
        parts: List[str] = []
        if mem.relationship:
            parts.append(mem.relationship)
        if mem.facts:
            parts.append(f"\n記住的事：\n{mem.facts}")
        return "\n".join(parts)

    def _resolve_path(self, key: str) -> Path:
        """
        將 conversation_id 映射到檔案路徑

        SESSION  ws:{token}             → memory/_sessions/ws_{token}.md
        DIRECT   {source}:dm:{user_id}  → memory/{character}/direct/{source}_dm_{user_id}.md
        GROUP    {source}:{room}:{id}   → memory/{character}/groups/{source}_{room}_{id}.md
        """
        safe = _sanitize_filename(key)

        if key.startswith("ws:"):
            return self._memory_dir / "_sessions" / f"{safe}.md"

        if ":dm:" in key and self._share_direct_memories:
            return self._memory_dir / "_shared" / "direct" / f"{safe}.md"

        if self._character:
            if ":dm:" in key:
                return self._memory_dir / self._character / "direct" / f"{safe}.md"
            return self._memory_dir / self._character / "groups" / f"{safe}.md"

        # 無角色時直接存在 memory 根目錄
        return self._memory_dir / f"{safe}.md"
