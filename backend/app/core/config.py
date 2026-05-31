from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
