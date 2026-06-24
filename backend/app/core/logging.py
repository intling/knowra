"""Structured logging for knowra.

Provides:
- ``KnowraLogger`` — a ``LoggerAdapter`` that auto-injects ``trace_id``
- ``ConsoleFormatter`` / ``JsonFormatter`` — dual-mode formatting
- ``configure_logging()`` — wires everything together
- ``get_logger()`` — factory for caller modules
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any

from app.core.trace_context import get_trace_id

# Sentinel that marks extra keys we add automatically.
_AUTO_KEYS = frozenset({"trace_id"})

# ANSI escape sequences for log levels.
_COLORS = {
    "DEBUG": "\033[34m",  # blue
    "INFO": "\033[32m",  # green
    "WARNING": "\033[33m",  # yellow
    "ERROR": "\033[31m",  # red
    "CRITICAL": "\033[35m",  # magenta
}
_RESET = "\033[0m"


# ---------------------------------------------------------------------------
# Logger adapter
# ---------------------------------------------------------------------------


class KnowraLogger(logging.LoggerAdapter):
    """Adapter that automatically injects ``trace_id`` from contextvars."""

    def __init__(self, logger: logging.Logger, extra: dict[str, Any] | None = None) -> None:
        super().__init__(logger, extra or {})

    def process(self, msg: Any, kwargs: Any) -> tuple[Any, Any]:
        """Merge trace_id and caller-supplied extra into the record."""
        kwargs = dict(kwargs) if kwargs else {}
        extra = dict(kwargs.get("extra", {}))
        extra.setdefault("trace_id", get_trace_id())
        kwargs["extra"] = extra
        return msg, kwargs


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


class ConsoleFormatter(logging.Formatter):
    """Human-readable formatter with ANSI colours and ``key=value`` extras."""

    def format(self, record: logging.LogRecord) -> str:
        colour = _COLORS.get(record.levelname, "")
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"

        # Build the base line.
        trace = getattr(record, "trace_id", "-")
        base = (
            f"{colour}{record.levelname:<8}{_RESET} "
            f"{ts} "
            f"[{trace}] "
            f"{record.name} — "
            f"{record.getMessage()}"
        )

        # Inline extra fields (everything beyond the logging built-ins and our autos).
        extra_parts = _build_extra_kv(record)
        if extra_parts:
            base += "  " + " ".join(extra_parts)

        if record.exc_info and record.exc_info[1]:
            base += "\n" + self.formatException(record.exc_info)

        return base


class JsonFormatter(logging.Formatter):
    """JSON Lines formatter — one JSON object per line, extra fields at root."""

    def format(self, record: logging.LogRecord) -> str:
        obj: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "trace_id": getattr(record, "trace_id", "-"),
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Flatten extra fields onto root.
        for key, val in _iter_extra(record):
            obj[key] = val

        if record.exc_info and record.exc_info[1]:
            obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(obj, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Built-in LogRecord attributes: don't repeat them as key=value extras.
_INTERNAL_RECORD_ATTRS: set[str] = {
    name
    for name in sorted(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)
    if not name.startswith("_")
}
_INTERNAL_RECORD_ATTRS |= {  # extra fields set by our adapter
    "trace_id",
    "message",
    "asctime",
}


def _build_extra_kv(record: logging.LogRecord) -> list[str]:
    """Return ``key=value`` strings for every non-internal record attribute."""
    parts: list[str] = []
    for key, val in _iter_extra(record):
        parts.append(f"{key}={val}")
    return parts


def _iter_extra(record: logging.LogRecord):
    """Yield (key, value) pairs for user-defined extra fields on *record*."""
    for key, val in sorted(record.__dict__.items()):
        if key in _INTERNAL_RECORD_ATTRS:
            continue
        yield key, val


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def configure_logging(
    debug: bool = True,
    log_level: str = "INFO",
    log_format: str = "",
    log_file_path: str = "logs/knowra.log",
    log_file_max_size: int = 10 * 1024 * 1024,
    log_file_backup_count: int = 5,
) -> None:
    """Set up log handlers and formatters for the whole application.

    Call once at startup (e.g. from ``create_app()``).
    """
    fmt = log_format or ("console" if debug else "json")
    level = _level_from_str(log_level)

    # Resolve root logger.
    root = logging.getLogger()
    root.setLevel(level)

    # Remove any pre-existing handlers (idempotent for tests).
    root.handlers.clear()

    # --- console handler ---
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(ConsoleFormatter() if fmt == "console" else JsonFormatter())
    root.addHandler(console)

    # --- file handler ---
    os.makedirs(os.path.dirname(log_file_path) or ".", exist_ok=True)
    file_handler = RotatingFileHandler(
        log_file_path,
        maxBytes=log_file_max_size,
        backupCount=log_file_backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(ConsoleFormatter() if fmt == "console" else JsonFormatter())
    root.addHandler(file_handler)


def get_logger(name: str) -> KnowraLogger:
    """Return a ``KnowraLogger`` that automatically carries ``trace_id``."""
    return KnowraLogger(logging.getLogger(name))


def _level_from_str(raw: str) -> int:
    try:
        return getattr(logging, raw.upper())
    except AttributeError:
        return logging.INFO
