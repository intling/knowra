"""Structured logging for knowra via structlog.

Provides:
- ``TraceFilter`` — injects ``trace_id`` into every LogRecord (root level)
- ``configure_logging()`` — wires structlog + stdlib handlers together
- ``get_logger()`` — factory returning a ``structlog.stdlib.BoundLogger``
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler

import structlog
from structlog.dev import ConsoleRenderer
from structlog.processors import JSONRenderer, TimeStamper, add_log_level, format_exc_info

from app.core.trace_context import get_trace_id

# ---------------------------------------------------------------------------
# TraceFilter — kept from previous implementation, unchanged
# ---------------------------------------------------------------------------


class TraceFilter(logging.Filter):
    """Inject ``trace_id`` from contextvars into every LogRecord.

    Applied on the root logger so that ALL log records — including those
    emitted by third-party libraries (SQLAlchemy, uvicorn, etc.) — carry
    the current request's trace_id without requiring the caller to use
    structlog.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "trace_id", None):
            record.trace_id = get_trace_id()
        return True


class HttpAccessDebugFilter(logging.Filter):
    """Demote HTTP access logs so request/response noise only appears in DEBUG."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "uvicorn.access" and record.levelno == logging.INFO:
            record.levelno = logging.DEBUG
            record.levelname = logging.getLevelName(logging.DEBUG)
        return True


# ---------------------------------------------------------------------------
# Processor helpers
# ---------------------------------------------------------------------------


def _trace_id_injector(_, __, event_dict: dict) -> dict:
    """structlog processor that injects ``trace_id`` from contextvars.

    Used in BOTH the structlog pre-chain and the ProcessorFormatter's
    foreign_pre_chain, so trace_id appears regardless of log source.
    """
    if "trace_id" not in event_dict:
        event_dict["trace_id"] = get_trace_id()
    return event_dict


# ── Foreign-record processors ────────────────────────────────────────────────
# These extract metadata from the stdlib LogRecord (stored as ``_record`` in
# the event dict) so that third-party / foreign log records are rendered with
# the same fields as structlog events.


def _foreign_add_level(_, __, event_dict: dict) -> dict:
    """Extract log level from the LogRecord for foreign (non-structlog) records."""
    record = event_dict.get("_record")
    if record is not None:
        event_dict.setdefault("level", record.levelname.lower())
    return event_dict


def _foreign_add_timestamp(_, __, event_dict: dict) -> dict:
    """Add an ISO-8601 timestamp for foreign records, matching structlog's format."""
    event_dict.setdefault(
        "timestamp",
        datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    )
    return event_dict


def _foreign_add_logger_name(_, __, event_dict: dict) -> dict:
    """Extract logger name from the LogRecord for foreign records."""
    record = event_dict.get("_record")
    if record is not None:
        event_dict.setdefault("logger", record.name)
    return event_dict


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _make_uvicorn_logging_config(level: int) -> dict:
    """Return a minimal logging config that neutralizes uvicorn's handlers.

    Uvicorn calls ``logging.config.dictConfig(LOGGING_CONFIG)`` during
    ``Server.run()``.  The default config adds uvicorn's own formatter and
    handler with ``propagate=False``.  We replace it with this stub that
    only sets ``propagate=True`` — all uvicorn records bubble up to root
    where our ``ProcessorFormatter`` and ``TraceFilter`` are installed.
    """
    level_name = logging.getLevelName(level)
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {},
        "handlers": {},
        "loggers": {
            "uvicorn": {"propagate": True},
            "uvicorn.error": {"level": level_name, "propagate": True},
            "uvicorn.access": {"level": level_name, "propagate": True},
        },
    }


def configure_logging(
    debug: bool = True,
    log_level: str = "INFO",
    log_format: str = "",
    log_file_path: str = "logs/knowra.log",
    log_file_max_size: int = 10 * 1024 * 1024,
    log_file_backup_count: int = 5,
) -> None:
    """Set up structlog + stdlib handlers for the whole application.

    Call once at startup (e.g. from ``create_app()``).

    Architecture:
    - structlog processors prepare the event dict (without rendering)
    - ``ProcessorFormatter`` on stdlib handlers does the final rendering,
      handling BOTH structlog events and raw stdlib LogRecords
    - ``TraceFilter`` on root logger injects trace_id for third-party libs
    """
    fmt = log_format or ("console" if debug else "json")
    level = _level_from_str(log_level)

    # --- Renderers ---
    # Console: human-readable with colours in debug mode, JSON in production.
    # File: always JSON Lines (one JSON object per line) for downstream ingestion.
    console_renderer = (
        ConsoleRenderer(pad_level=False, pad_event_to=0) if fmt == "console" else JSONRenderer()
    )
    file_renderer = JSONRenderer(
        serializer=lambda obj, **kw: json.dumps(obj, ensure_ascii=False, **kw)
    )

    # --- structlog: prepare event dict, don't render ---
    # ``wrap_for_formatter`` stores the event dict on the LogRecord so that
    # ``ProcessorFormatter`` can retrieve and render it later.  Without this
    # processor the event dict would be lost and only a raw string passed.
    structlog.configure(
        processors=[
            _trace_id_injector,
            add_log_level,
            TimeStamper(fmt="iso"),
            structlog.stdlib.add_logger_name,
            format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # --- stdlib handler setup ---
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.filters.clear()

    root.addFilter(TraceFilter())

    # ProcessorFormatter renders BOTH structlog events and foreign LogRecords.
    # ``foreign_pre_chain`` enriches non-structlog records (SQLAlchemy, uvicorn,
    # docling, etc.) with level, timestamp, logger name, and trace_id so they
    # look the same as structlog events.
    console_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[
            _foreign_add_level,
            _foreign_add_timestamp,
            _foreign_add_logger_name,
            _trace_id_injector,
            format_exc_info,
        ],
        processor=console_renderer,
    )

    # File formatter: same enrichment, but always renders as JSON.
    file_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[
            _foreign_add_level,
            _foreign_add_timestamp,
            _foreign_add_logger_name,
            _trace_id_injector,
            format_exc_info,
        ],
        processor=file_renderer,
    )

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(console_formatter)
    root.addHandler(console)

    # File handler — always JSON Lines format
    os.makedirs(os.path.dirname(log_file_path) or ".", exist_ok=True)
    file_handler = RotatingFileHandler(
        log_file_path,
        maxBytes=log_file_max_size,
        backupCount=log_file_backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(file_formatter)
    root.addHandler(file_handler)

    # --- Third-party logger integration ---
    # SQLAlchemy
    for _name in ("sqlalchemy.engine", "sqlalchemy.engine.Engine", "sqlalchemy.pool"):
        _sqla = logging.getLogger(_name)
        _sqla.handlers.clear()
        _sqla.propagate = True
        _sqla.setLevel(logging.DEBUG if level <= logging.DEBUG else logging.WARNING)

    # Docling — ensure its logs propagate through our formatter
    for _name in ("docling", "docling_core"):
        _logger = logging.getLogger(_name)
        _logger.propagate = True

    # --- Uvicorn: neutralize its built-in logging config ---
    #
    # Uvicorn's ``Server.run()`` calls ``config.configure_logging()`` AFTER the
    # app module is imported.  That applies a ``dictConfig`` which resets
    # uvicorn's internal loggers with ``propagate=False`` and its own handler.
    # If we don't interfere here, the early startup messages ("Started server
    # process", "Waiting for application startup") would use uvicorn's native
    # format instead of our ProcessorFormatter.
    #
    # We replace uvicorn's LOGGING_CONFIG with a minimal version that only
    # enables propagation — all records bubble up to root, through our
    # ProcessorFormatter + TraceFilter.
    _uvicorn_cfg = _make_uvicorn_logging_config(level)
    import uvicorn.config as _uv_config

    _uv_config.LOGGING_CONFIG = _uvicorn_cfg

    # Pre-configure uvicorn loggers now so that even before uvicorn runs its
    # (now-harmless) dictConfig, any messages go through our formatter.
    configure_uvicorn_loggers()


def configure_uvicorn_loggers() -> None:
    _trace_filter = TraceFilter()
    _access_filter = HttpAccessDebugFilter()
    for _name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        _uvi = logging.getLogger(_name)
        _uvi.handlers.clear()
        _uvi.filters.clear()
        _uvi.propagate = True
        _uvi.addFilter(_trace_filter)
        if _name == "uvicorn.access":
            _uvi.addFilter(_access_filter)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog ``BoundLogger`` that automatically carries ``trace_id``."""
    return structlog.get_logger(name)


def _level_from_str(raw: str) -> int:
    try:
        return getattr(logging, raw.upper())
    except AttributeError:
        return logging.INFO
