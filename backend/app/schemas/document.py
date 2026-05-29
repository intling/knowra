from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer


class DocumentCreate(BaseModel):
    uploaded_file_id: UUID


class SourceFileRead(BaseModel):
    id: UUID
    original_filename: str
    content_type: str | None
    byte_size: int
    status: str

    model_config = ConfigDict(from_attributes=True)


class DocumentRead(BaseModel):
    id: UUID
    owner_user_id: UUID
    uploaded_file_id: UUID
    title: str
    source_content_type: str | None
    parser_name: str | None
    parser_version: str | None
    chunker_name: str | None
    chunker_version: str | None
    tokenizer_name: str | None
    tokenizer_version: str | None
    status: str
    chunk_count: int
    total_chars: int
    content_sha256: str | None
    metadata_json: dict[str, Any]
    error_message: str | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    source_file: SourceFileRead | None

    @field_serializer("deleted_at", "created_at", "updated_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        if value is None:
            return None

        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)

        return value.isoformat().replace("+00:00", "Z")


class DocumentChunkRead(BaseModel):
    id: UUID
    document_id: UUID
    owner_user_id: UUID
    chunk_index: int
    content: str
    content_sha256: str
    char_start: int
    char_end: int
    token_count: int
    source_locator_json: dict[str, Any]
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("created_at", "updated_at")
    def serialize_datetime(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)

        return value.isoformat().replace("+00:00", "Z")
