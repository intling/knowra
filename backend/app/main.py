"""FastAPI application factory for knowra."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.logging import TraceFilter, configure_logging
from app.middleware.trace import TraceMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Reconfigure uvicorn loggers so they propagate through our formatters.

    Uvicorn's ``configure_logging()`` (called during server startup) applies a
    ``dictConfig`` that sets ``propagate=False`` on its internal loggers.  This
    lifespan handler runs *after* that, removing uvicorn's handlers and letting
    the records bubble up to the root logger so they carry a ``trace_id`` and
    use our structured formatters.
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
    app.add_middleware(TraceMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestLoggingMiddleware)
    app.include_router(api_router, prefix=app_settings.api_prefix)

    return app


app = create_app()
