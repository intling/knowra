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

DEFAULT_DOCUMENT_MODEL_DOCLING_REQUIRED_MODELS = (
    "layout",
    "tableformer",
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
    document_embedding_enabled: bool = True
    document_embedding_api_base_url: str = "https://router.tumuer.me/v1"
    document_embedding_api_key: str = ""
    document_embedding_model: str = "Qwen/Qwen3-Embedding-4B"
    document_embedding_dimensions: int = 2560
    document_embedding_encoding_format: str = "float"
    document_embedding_batch_size: int = 100
    document_embedding_max_retries: int = 3
    document_embedding_request_timeout: float = 60.0
    document_model_bootstrap_enabled: bool = True
    document_model_bootstrap_strategy: str = "download_missing"
    document_model_bootstrap_failure_policy: str = "degraded"
    document_model_docling_artifact_dir: str = "storage/document-models/docling"
    document_model_hf_endpoint: str = ""
    document_model_docling_required_models: Annotated[list[str], NoDecode] = list(
        DEFAULT_DOCUMENT_MODEL_DOCLING_REQUIRED_MODELS
    )
    document_model_tokenizer_name: str = "Qwen/Qwen2-7B"
    document_model_tokenizer_cache_dir: str = "storage/document-models/tokenizers"
    document_model_shutdown_timeout_seconds: float = 5.0

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

    @field_validator("document_model_docling_required_models", mode="before")
    @classmethod
    def parse_document_model_docling_required_models(cls, value: str | list[str]) -> list[str]:
        return parse_csv_list(value)

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
