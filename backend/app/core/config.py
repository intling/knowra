from functools import lru_cache
from typing import Annotated

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_ALLOWED_UPLOAD_CONTENT_TYPES = (
    "application/pdf",
    "text/markdown",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
)

DEFAULT_DOCUMENT_PARSE_ALLOWED_CONTENT_TYPES = (
    "application/pdf",
    "text/markdown",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
)

DEFAULT_DOCUMENT_PARSE_ALLOWED_EXTENSIONS = (
    ".docx",
    ".md",
    ".markdown",
    ".pdf",
    ".pptx",
    ".txt",
)


class Settings(BaseSettings):
    app_name: str = "knowra"
    app_env: str = "local"
    debug: bool = True
    log_level: str = "INFO"
    api_prefix: str = "/api"
    backend_cors_origins: str = "http://localhost:5173"
    database_url: str = "postgresql+psycopg://knowra:knowra@localhost:5432/knowra"
    upload_storage_dir: str = "storage/uploads"
    max_upload_bytes: int = 50 * 1024 * 1024
    allowed_upload_content_types: Annotated[list[str], NoDecode] = list(
        DEFAULT_ALLOWED_UPLOAD_CONTENT_TYPES
    )
    document_parse_enabled: bool = True
    document_parse_artifact_dir: str = "storage/parsed"
    document_parse_max_bytes: int = 50 * 1024 * 1024
    document_parse_max_pages: int = 100
    document_parse_ocr_enabled: bool = False
    document_parse_docling_cache_dir: str = "storage/docling-cache"
    document_parse_dispatcher: str = "background_tasks"
    document_parse_allowed_content_types: Annotated[list[str], NoDecode] = list(
        DEFAULT_DOCUMENT_PARSE_ALLOWED_CONTENT_TYPES
    )
    document_parse_allowed_extensions: Annotated[list[str], NoDecode] = list(
        DEFAULT_DOCUMENT_PARSE_ALLOWED_EXTENSIONS
    )
    document_chunking_enabled: bool = True
    document_chunk_max_tokens: int = 512
    document_chunk_tokenizer_model: str = "Qwen/Qwen2-7B"
    document_chunk_merge_peers: bool = True
    document_chunk_repeat_table_header: bool = True
    document_chunk_inline_text_max_bytes: int = 2048
    document_chunk_artifact_storage_dir: str = "storage/chunks"

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
        return parse_csv_list(value)

    @field_validator("document_parse_allowed_content_types", mode="before")
    @classmethod
    def parse_document_parse_allowed_content_types(cls, value: str | list[str]) -> list[str]:
        return parse_csv_list(value)

    @field_validator("document_parse_allowed_extensions", mode="before")
    @classmethod
    def parse_document_parse_allowed_extensions(cls, value: str | list[str]) -> list[str]:
        return [extension.lower() for extension in parse_csv_list(value)]

    @model_validator(mode="after")
    def _resolve_log_format(self) -> Settings:
        if not self.log_format:
            self.log_format = "console" if self.debug else "json"
        return self


def parse_csv_list(value: str | list[str]) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]

    return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
