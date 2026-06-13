from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_serializer


class DocumentChunkJobRead(BaseModel):
    id: UUID
    parsed_document_id: UUID
    owner_user_id: UUID
    status: str
    chunker_name: str
    chunker_version: str | None
    chunk_config_json: dict | None
    chunk_count: int
    attempt_count: int
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("started_at", "finished_at", "created_at", "updated_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        if value is None:
            return None

        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)

        return value.isoformat().replace("+00:00", "Z")


class DocumentChunkRead(BaseModel):
    id: UUID
    chunk_job_id: UUID
    parsed_document_id: UUID
    owner_user_id: UUID
    sequence_index: int
    text: str | None
    contextualized_text: str | None
    token_count: int | None
    heading_path: list[str] | None
    page_numbers: list[int] | None
    chunk_type: str | None
    source_segment_indices: list[int] | None
    metadata: dict | None
    created_at: datetime

    @field_serializer("created_at")
    def serialize_datetime(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)

        return value.isoformat().replace("+00:00", "Z")


class DocumentChunkPageRead(BaseModel):
    items: list[DocumentChunkRead]
    total: int
    offset: int
    limit: int


class DocumentChunkConflictRead(BaseModel):
    detail: str
    job: DocumentChunkJobRead


class RechunkRequest(BaseModel):
    max_tokens: int | None = Field(default=None, ge=1)
    tokenizer_model: str | None = None
    merge_peers: bool | None = None
    repeat_table_header: bool | None = None
