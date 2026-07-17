from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import UtcDateTime


class EmbeddingJobResponse(BaseModel):
    id: UUID
    chunk_job_id: UUID
    parsed_document_id: UUID
    owner_user_id: UUID
    status: str
    embedder_name: str
    model: str
    dimensions: int
    embedding_count: int
    attempt_count: int
    started_at: UtcDateTime | None
    finished_at: UtcDateTime | None
    error_code: str | None
    error_message: str | None
    config_json: dict | None
    created_at: UtcDateTime
    updated_at: UtcDateTime


class EmbeddingResponse(BaseModel):
    id: UUID
    chunk_id: UUID
    embedding_job_id: UUID
    sequence_index: int
    model: str
    dimensions: int
    embedding_json: list[float]
    token_count: int | None
    created_at: UtcDateTime


class ReEmbedRequest(BaseModel):
    model: str | None = None
    dimensions: int | None = None


class EmbeddingPageResponse(BaseModel):
    items: list[EmbeddingResponse]
    total: int
    offset: int
    limit: int


class EmbeddingConflictResponse(BaseModel):
    detail: str
    job: EmbeddingJobResponse
