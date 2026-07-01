"""Structured logging for knowra via structlog.

Provides:
- ``TraceFilter`` — injects ``trace_id`` into every LogRecord (root level)
- ``configure_logging()`` — wires structlog + stdlib handlers together
- ``get_logger()`` — factory returning a ``structlog.stdlib.BoundLogger``
"""

from __future__ import annotations

import logging
import os
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

    # --- Renderer (used by ProcessorFormatter, not in structlog chain) ---
    renderer = ConsoleRenderer() if fmt == "console" else JSONRenderer()

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

    # ProcessorFormatter renders BOTH structlog events and foreign LogRecords
    handler_fmt = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[
            _trace_id_injector,
            format_exc_info,
        ],
        processor=renderer,
    )

    # Console handler
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(handler_fmt)
    root.addHandler(console)

    # File handler
    os.makedirs(os.path.dirname(log_file_path) or ".", exist_ok=True)
    file_handler = RotatingFileHandler(
        log_file_path,
        maxBytes=log_file_max_size,
        backupCount=log_file_backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(handler_fmt)
    root.addHandler(file_handler)

    # --- Third-party logger integration ---
    for _name in ("sqlalchemy.engine", "sqlalchemy.engine.Engine", "sqlalchemy.pool"):
        _sqla = logging.getLogger(_name)
        _sqla.handlers.clear()
        _sqla.propagate = True
        _sqla.setLevel(logging.DEBUG if level <= logging.DEBUG else logging.WARNING)

    _trace_filter = TraceFilter()
    for _name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(_name).addFilter(_trace_filter)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog ``BoundLogger`` that automatically carries ``trace_id``."""
    return structlog.get_logger(name)


def _level_from_str(raw: str) -> int:
    try:
        return getattr(logging, raw.upper())
    except AttributeError:
        return logging.INFO
