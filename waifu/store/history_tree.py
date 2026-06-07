from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from waifu.logger import logger
from waifu_types import AssistantMessage, BaseMessage, HookContext, SystemMessage

_MEMORY_MARKER = "[history_tree_memory]"


def _dump_for_log(payload: Any) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    except TypeError:
        return str(payload)


def _safe_document_name(key: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in key).strip("._")
    if not cleaned:
        cleaned = "document"
    if not cleaned.endswith(".md"):
        cleaned = f"{cleaned}.md"
    return cleaned


def _describe_request_error(exc: Exception) -> str:
    try:
        import httpx
    except ImportError:  # pragma: no cover
        httpx = None  # type: ignore[assignment]

    if httpx is not None and isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        body = response.text.strip().replace("\n", " ")
        if len(body) > 240:
            body = body[:237] + "..."
        suffix = f"; body={body}" if body else ""
        return f"{type(exc).__name__}: {response.status_code} {response.reason_phrase}{suffix}"

    if httpx is not None and isinstance(exc, httpx.TimeoutException):
        request = getattr(exc, "request", None)
        method = getattr(request, "method", "request")
        url = getattr(request, "url", "?")
        return f"{type(exc).__name__}: timed out calling {method} {url}"

    detail = str(exc).strip()
    if detail:
        return f"{type(exc).__name__}: {detail}"
    return type(exc).__name__


def _message_text(message: BaseMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: List[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                chunks.append(str(part["text"]).strip())
        return "\n".join(filter(None, chunks))
    return str(content).strip()


def _render_query_summary(payload: Dict[str, Any]) -> str:
    lines: List[str] = []

    facts = payload.get("facts") or []
    if facts:
        lines.append("## Relevant Facts")
        for fact in facts[:8]:
            if not isinstance(fact, dict):
                continue
            subject = fact.get("subject") or "?"
            predicate = fact.get("predicate") or "related_to"
            obj = fact.get("object") or "?"
            status = fact.get("status")
            if status:
                lines.append(f"- {subject} {predicate} {obj} ({status})")
            else:
                lines.append(f"- {subject} {predicate} {obj}")
        lines.append("")

    entities = payload.get("entities") or []
    if entities:
        lines.append("## Relevant Entities")
        for entity in entities[:8]:
            if not isinstance(entity, dict):
                continue
            name = entity.get("name") or entity.get("id") or "unknown"
            entity_type = entity.get("type") or entity.get("entity_type")
            description = entity.get("description")
            extra = f" ({entity_type})" if entity_type else ""
            if description:
                lines.append(f"- {name}{extra}: {description}")
            else:
                lines.append(f"- {name}{extra}")
        lines.append("")

    chunks = payload.get("chunks") or []
    if chunks:
        lines.append("## Supporting Excerpts")
        for chunk in chunks[:4]:
            if not isinstance(chunk, dict):
                continue
            text = str(chunk.get("text") or "").strip()
            source = chunk.get("source")
            if not text:
                continue
            if len(text) > 280:
                text = text[:277] + "..."
            if source:
                lines.append(f"- {text} [source: {source}]")
            else:
                lines.append(f"- {text}")

    return "\n".join(lines).strip()


def _render_turn_document(
    ctx: HookContext,
    *,
    memory_key: str,
    character_name: Optional[str],
    assistant_messages: Iterable[BaseMessage],
) -> str:
    now = datetime.now(timezone.utc).isoformat()
    lines = [
        "## Metadata",
        f"- memory_key: {memory_key}",
        f"- recorded_at: {now}",
        f"- user_id: {ctx.request.sender.user_id}",
        f"- display_name: {ctx.request.sender.display_name}",
    ]
    if character_name:
        lines.append(f"- character: {character_name}")

    lines.extend(
        [
            "",
            "## Dialogue",
            f"User ({ctx.request.sender.display_name}): {ctx.request.content.strip()}",
        ]
    )

    for message in assistant_messages:
        text = _message_text(message)
        if text:
            lines.append(f"Assistant: {text}")

    return "\n".join(lines).strip() + "\n"


class HistoryTreeStore:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_s: float = 10.0,
        top_k: int = 5,
        rerank: bool = False,
        query_graph: str = "world",
        ingest_graph: str = "world",
        character_name: Optional[str] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._top_k = top_k
        self._rerank = rerank
        self._query_graph = query_graph
        self._ingest_graph = ingest_graph
        self._character_name = character_name

    async def load(self, _key: str) -> List[BaseMessage]:
        return []

    async def load_for_context(self, ctx: HookContext, key: str) -> List[BaseMessage]:
        import httpx

        query = ctx.request.content.strip()
        if not query:
            return []

        query_payload = {
            "query": query,
            "top_k": self._top_k,
            "rerank": self._rerank,
            "graph": self._query_graph,
        }
        logger.debug(
            "HistoryTree query request for key {} -> POST {}/query\n{}",
            key,
            self._base_url,
            _dump_for_log(query_payload),
        )

        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                resp = await client.post(
                    f"{self._base_url}/query",
                    json=query_payload,
                )
                resp.raise_for_status()
        except Exception as exc:
            logger.warning("HistoryTree query failed for key {}: {}", key, _describe_request_error(exc))
            return []

        summary = _render_query_summary(resp.json())
        if not summary:
            return []

        return [
            SystemMessage(
                content=(
                    f"{_MEMORY_MARKER}\n"
                    "以下是與當前問題相關的長期記憶，僅供參考；若與使用者最新訊息衝突，以最新訊息為準。\n"
                    f"{summary}"
                )
            )
        ]

    async def save(self, _key: str, _messages: List[BaseMessage]) -> None:
        return None

    async def save_for_context(self, ctx: HookContext, key: str, _messages: List[BaseMessage]) -> None:
        import httpx

        assistant_messages = [msg for msg in ctx.new_messages if isinstance(msg, AssistantMessage)]
        if not assistant_messages and not (ctx.response or "").strip():
            return
        if not assistant_messages and (ctx.response or "").strip():
            assistant_messages = [AssistantMessage(content=ctx.response)]

        document = _render_turn_document(
            ctx,
            memory_key=key,
            character_name=self._character_name,
            assistant_messages=assistant_messages,
        )

        try:
            ingest_payload = {
                "text": document,
                "name": _safe_document_name(key),
                "graph": self._ingest_graph,
            }
            logger.debug(
                "HistoryTree ingest request for key {} -> POST {}/documents\npayload={}\ndocument=\n{}",
                key,
                self._base_url,
                _dump_for_log(ingest_payload),
                document,
            )

            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                resp = await client.post(
                    f"{self._base_url}/documents",
                    json=ingest_payload,
                )
                resp.raise_for_status()
        except Exception as exc:
            logger.warning(
                "HistoryTree ingest failed for key {} (graph={}, name={}): {}",
                key,
                self._ingest_graph,
                ingest_payload.get("name"),
                _describe_request_error(exc),
            )

    async def clear(self, key: str) -> None:
        logger.debug("HistoryTreeStore.clear({}) is a no-op; archive semantics are not implemented yet", key)


__all__ = ["HistoryTreeStore"]
