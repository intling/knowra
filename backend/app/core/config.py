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
    chat_api_base_url: str = "https://newapi.bytcloud.org/v1"
    chat_api_key: str = ""
    chat_model: str = "qwen3.5-plus"
    chat_temperature: float = 0.1
    chat_max_tokens: int = 1024
    chat_request_timeout: float = 60.0
    chat_max_retries: int = 3
    # 查询重写（Query Rewriting）配置
    query_rewrite_enabled: bool = False
    query_rewrite_model: str = "qwen3.5-plus"
    query_rewrite_temperature: float = 0.1
    query_rewrite_max_tokens: int = 512
    query_rewrite_timeout: float = 30.0
    query_rewrite_max_retries: int = 3
    query_rewrite_api_base_url: str = "https://newapi.bytcloud.org/v1"
    query_rewrite_api_key: str = ""
    query_rewrite_pipeline_timeout: float = 3.0
    # 语义搜索相似度阈值（余弦距离，0-2。0=完全相同，2=完全相反）
    # 仅当分块与查询的余弦距离 <= 此阈值时才纳入检索结果。
    # 设 0 表示禁用过滤。推荐值 0.4-0.6（取决于嵌入模型）。
    # 应与 search_min_score_threshold 保持 0.1-0.15 差距，确保两道防线分工明确。
    search_similarity_threshold: float = 0.55

    # 语义搜索最低分数阈值（余弦距离，0-2）。
    # 检索结果中最优分块（最低余弦距离）必须 <= 此阈值，否则视为"无相关结果"，
    # 返回空结果且不调用 LLM。这是防止 LLM 基于弱相关内容产生幻觉的第二道防线。
    # 应设置得比 search_similarity_threshold 更严格（值更小）。
    # 设 0 表示禁用此检查。
    search_min_score_threshold: float = 0.45
    # 搜索响应 L1 缓存（内存 LRU，会话绑定精确匹配）
    # 缓存完整的 SearchResponse（含自然语言回答、引用文档片段、模型版本、
    # Token 消耗、生成耗时、审计追踪 ID），相同会话内完全相同的查询直接返回缓存结果。
    # 设 False 可完全禁用；TTL 和 max_size 仅在启用时生效。
    search_cache_enabled: bool = True
    search_cache_ttl_seconds: float = 600.0  # 10 分钟
    search_cache_max_size: int = 100
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
