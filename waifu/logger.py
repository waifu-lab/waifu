from __future__ import annotations

import contextvars
import logging
import sys
from pathlib import Path
from typing import Optional, Union

from loguru import logger
from rich.highlighter import NullHighlighter, ReprHighlighter
from rich.logging import RichHandler
from rich.text import Text

cid: contextvars.ContextVar[str] = contextvars.ContextVar("cid", default="-")
_MESSAGE_SPLIT = "__WAIFU_MESSAGE_SPLIT__"


def _patch(record: dict) -> None:
    record["extra"].setdefault("cid", cid.get())
    record["extra"].setdefault("logger_name", record["name"])


class _InterceptHandler(logging.Handler):
    """Route stdlib logging records into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.bind(logger_name=record.name).opt(
            depth=depth,
            exception=record.exc_info,
        ).log(level, record.getMessage())


class _MessageOnlyRichHandler(RichHandler):
    """Highlight only the message body while keeping the prefix untouched."""

    _message_highlighter = ReprHighlighter()

    def render_message(self, record: logging.LogRecord, message: str):
        if _MESSAGE_SPLIT not in message:
            return super().render_message(record, message)

        prefix, _, body = message.partition(_MESSAGE_SPLIT)

        if getattr(record, "markup", self.markup):
            prefix_text = Text.from_markup(prefix)
            body_text = Text.from_markup(body)
        else:
            prefix_text = Text(prefix)
            body_text = Text(body)

        body_text = self._message_highlighter(body_text)
        prefix_text.append_text(body_text)
        return prefix_text


_configured = False


def setup_logging(
    level: str = "INFO",
    log_file: Optional[Union[str, Path]] = None,
    *,
    rich_tracebacks: bool = True,
    serialize_file: bool = True,
) -> None:
    """Configure loguru sinks. Idempotent — safe to call multiple times."""
    global _configured

    logger.remove()
    logger.configure(patcher=_patch)

    prefix_fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
        "<level>{level: <8}</level> "
        "<cyan>[{extra[cid]}]</cyan> "
        "<cyan>{extra[logger_name]}</cyan>:<dim>{function}:{line}</dim> - "
    )
    console_fmt = f"{prefix_fmt}{_MESSAGE_SPLIT}{{message}}"
    file_fmt = f"{prefix_fmt}<level>{{message}}</level>"

    logger.add(
        _MessageOnlyRichHandler(
            rich_tracebacks=rich_tracebacks,
            markup=False,
            show_time=False,
            show_level=False,
            show_path=False,
            highlighter=NullHighlighter(),
            keywords=[],
        ),
        level=level.upper(),
        format=console_fmt,
        backtrace=rich_tracebacks,
        diagnose=rich_tracebacks,
    )

    if log_file:
        logger.add(
            str(log_file),
            level=level.upper(),
            serialize=serialize_file,
            rotation="1 day",
            retention="14 days",
            compression="zip",
            enqueue=True,
            format=file_fmt,
        )

    root = logging.getLogger()
    root.handlers = [_InterceptHandler()]
    root.setLevel(level.upper())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True

    _configured = True


__all__ = ["logger", "cid", "setup_logging"]
