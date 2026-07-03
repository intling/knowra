"""FastAPI application factory for knowra."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.logging import TraceFilter, configure_logging

# ── Configure logging BEFORE any app module that logs at import time ──────────
# db/session.py creates the engine and logs "数据库引擎已创建" at module
# level.  Calling configure_logging() here ensures structlog is wired up
# before those imports run.
_settings = get_settings()
configure_logging(
    debug=_settings.debug,
    log_level=_settings.log_level,
    log_format=_settings.log_format,
    log_file_path=_settings.log_file_path,
    log_file_max_size=_settings.log_file_max_size,
    log_file_backup_count=_settings.log_file_backup_count,
)

# Safe to import modules that create loggers at import time now.
from app.api.router import api_router  # noqa: E402
from app.core.middleware import RequestLoggingMiddleware  # noqa: E402
from app.middleware.trace import TraceMiddleware  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Belt-and-suspenders: ensure uvicorn loggers propagate through our formatters.

    ``configure_logging()`` already replaces uvicorn's default LOGGING_CONFIG
    with a neutral version, so uvicorn records flow through our
    ``ProcessorFormatter`` from the very first log line.  This lifespan
    handler re-applies the fix just in case something else re-confiqures
    uvicorn's loggers before startup.
    """
    _trace_filter = TraceFilter()
    for _name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        _uvi = logging.getLogger(_name)
        _uvi.handlers.clear()
        _uvi.filters.clear()
        _uvi.propagate = True
        _uvi.addFilter(_trace_filter)

    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    # configure_logging() already called at module level above — settings
    # passed here are from test overrides; reconfigure only if different.
    if settings is not None:
        configure_logging(
            debug=app_settings.debug,
            log_level=app_settings.log_level,
            log_format=app_settings.log_format,
            log_file_path=app_settings.log_file_path,
            log_file_max_size=app_settings.log_file_max_size,
            log_file_backup_count=app_settings.log_file_backup_count,
        )

    app = FastAPI(
        title=app_settings.app_name,
        debug=app_settings.debug,
        lifespan=lifespan,
    )
    # TraceMiddleware must be outermost so trace_id is set in the same
    # asyncio task before any child middleware creates subtasks.  Any
    # asyncio subtask created by inner BaseHTTPMiddleware inherits the
    # contextvar value, but cannot propagate changes back to its parent.
    #
    # In Starlette 1.0.0, add_middleware uses insert(0, …): the last
    # middleware added becomes the outermost.
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(TraceMiddleware)
    app.include_router(api_router, prefix=app_settings.api_prefix)

    return app


app = create_app()
