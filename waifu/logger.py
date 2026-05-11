"""Centralized logging for waifu using loguru + rich.

Usage:
    from waifu.logger import logger, cid

    cid.set("conv-123")
    logger.info("hello")

`cid` is a contextvars.ContextVar bound to the current conversation/request id;
it is automatically attached to every log record under `extra.cid`.

Standard `logging` calls (`logging.getLogger(...)`) are intercepted and routed
through loguru, so third-party libraries and existing modules using stdlib
logging share the same sinks/format.
"""

from __future__ import annotations

import contextvars
import logging
import sys
from pathlib import Path
from typing import Optional, Union

from loguru import logger
from rich.logging import RichHandler

cid: contextvars.ContextVar[str] = contextvars.ContextVar("cid", default="-")


def _patch(record: dict) -> None:
    record["extra"].setdefault("cid", cid.get())


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

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


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

    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
        "<level>{level: <8}</level> "
        "<cyan>[{extra[cid]}]</cyan> "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    logger.add(
        RichHandler(
            rich_tracebacks=rich_tracebacks,
            markup=False,
            show_path=False,
            log_time_format="[%X]",
        ),
        level=level.upper(),
        format="[{extra[cid]}] {name}:{function}:{line} - {message}",
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
            format=fmt,
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
