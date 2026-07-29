"""FastAPI application factory for knowra."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, configure_uvicorn_loggers

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
from app.core.shutdown import (  # noqa: E402
    ApplicationShutdownCoordinator,
    ApplicationShutdownState,
    default_shutdown_session_factory,  # noqa: E402
    reconcile_stale_jobs_at_startup,
)
from app.middleware.trace import TraceMiddleware  # noqa: E402
from app.services.document_model_bootstrap import DocumentModelBootstrapService  # noqa: E402
from app.services.document_model_runtime import (  # noqa: E402
    DocumentModelPreloader,
    DocumentModelRuntime,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Belt-and-suspenders: ensure uvicorn loggers propagate through our formatters.

    ``configure_logging()`` already replaces uvicorn's default LOGGING_CONFIG
    with a neutral version, so uvicorn records flow through our
    ``ProcessorFormatter`` from the very first log line.  This lifespan
    handler re-applies the fix just in case something else re-confiqures
    uvicorn's loggers before startup.
    """
    configure_uvicorn_loggers()
    if not hasattr(app.state, "application_shutdown_state") or getattr(
        app.state.application_shutdown_state,
        "is_shutting_down",
        False,
    ):
        app.state.application_shutdown_state = ApplicationShutdownState()
        app.state.application_shutdown_coordinator = None

    if not getattr(app.state, "startup_job_reconciliation_done", False):
        # 修复上一个进程非优雅退出（kill -9 / OOM 等）遗留的 queued/running 任务，
        # 否则它们会永久卡住后续 rechunk/re-embed 的 409 冲突检查。
        reconcile_stale_jobs_at_startup(
            session_factory=app.state.application_shutdown_session_factory
        )
        app.state.startup_job_reconciliation_done = True

    if not hasattr(app.state, "document_model_readiness"):
        bootstrap_factory = app.state.document_model_bootstrap_service_factory
        runtime_factory = app.state.document_model_runtime_factory
        bootstrap_readiness = bootstrap_factory().run()
        runtime = runtime_factory(bootstrap_readiness)
        app.state.document_model_readiness = runtime
        runtime.start_async()

    try:
        yield
    finally:
        coordinator = getattr(app.state, "application_shutdown_coordinator", None)
        if coordinator is None:
            coordinator = app.state.application_shutdown_coordinator_factory()
            app.state.application_shutdown_coordinator = coordinator
        coordinator.shutdown()


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
    app.state.settings = app_settings
    app.state.document_model_bootstrap_service_factory = lambda: DocumentModelBootstrapService(
        settings=app_settings
    )
    app.state.document_model_runtime_factory = lambda readiness: (
        DocumentModelRuntime.from_bootstrap_readiness(
            readiness,
            preloader=DocumentModelPreloader(settings=app_settings),
        )
    )
    app.state.application_shutdown_state = ApplicationShutdownState()
    app.state.application_shutdown_session_factory = default_shutdown_session_factory
    app.state.application_shutdown_coordinator_factory = lambda: ApplicationShutdownCoordinator(
        app=app,
        shutdown_state=get_or_create_shutdown_state(app),
        model_shutdown_timeout_seconds=app_settings.document_model_shutdown_timeout_seconds,
        session_factory=app.state.application_shutdown_session_factory,
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


def get_or_create_shutdown_state(app: FastAPI) -> ApplicationShutdownState:
    if not hasattr(app.state, "application_shutdown_state"):
        app.state.application_shutdown_state = ApplicationShutdownState()
    return app.state.application_shutdown_state


app = create_app()
