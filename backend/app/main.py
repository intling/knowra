from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.middleware.trace import TraceMiddleware


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

    app = FastAPI(title=app_settings.app_name, debug=app_settings.debug)
    app.add_middleware(TraceMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix=app_settings.api_prefix)

    return app


app = create_app()
