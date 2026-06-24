from functools import lru_cache
from typing import Annotated

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_ALLOWED_UPLOAD_CONTENT_TYPES = (
    "application/pdf",
    "text/markdown",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
)


class Settings(BaseSettings):
    app_name: str = "knowra"
    app_env: str = "local"
    debug: bool = True
    api_prefix: str = "/api"
    backend_cors_origins: str = "http://localhost:5173"
    database_url: str = "postgresql+psycopg://knowra:knowra@localhost:5432/knowra"
    upload_storage_dir: str = "storage/uploads"
    max_upload_bytes: int = 20 * 1024 * 1024
    allowed_upload_content_types: Annotated[list[str], NoDecode] = list(
        DEFAULT_ALLOWED_UPLOAD_CONTENT_TYPES
    )

    # --- logging ---
    log_level: str = "INFO"
    log_format: str = ""  # empty → auto-detect from debug
    log_file_path: str = "logs/knowra.log"
    log_file_max_size: int = 10 * 1024 * 1024  # 10 MB
    log_file_backup_count: int = 5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, value: bool | str) -> bool:
        if isinstance(value, str) and value.strip().lower() in {"release", "prod", "production"}:
            return False

        return value

    @field_validator("allowed_upload_content_types", mode="before")
    @classmethod
    def parse_allowed_upload_content_types(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [
                content_type.strip() for content_type in value.split(",") if content_type.strip()
            ]

        return value

    @model_validator(mode="after")
    def _resolve_log_format(self) -> "Settings":
        if not self.log_format:
            self.log_format = "console" if self.debug else "json"
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
