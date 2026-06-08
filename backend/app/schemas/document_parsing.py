from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, field_serializer


class UploadedFileParseInfo(BaseModel):
    id: UUID
    original_filename: str
    content_type: str | None
    byte_size: int
    status: str


class DocumentParseJobRead(BaseModel):
    id: UUID
    uploaded_file_id: UUID
    owner_user_id: UUID
    status: str
    parser_name: str
    parser_version: str | None
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


class DocumentParseConflictRead(BaseModel):
    detail: str
    job: DocumentParseJobRead
    uploaded_file: UploadedFileParseInfo


class ParsedDocumentRead(BaseModel):
    id: UUID
    uploaded_file_id: UUID
    parse_job_id: UUID
    owner_user_id: UUID
    source_checksum_sha256: str | None
    markdown_storage_key: str
    text_storage_key: str
    docling_json_storage_key: str
    title: str | None
    page_count: int | None
    metadata: dict | None
    segment_count: int
    created_at: datetime

    @field_serializer("created_at")
    def serialize_datetime(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)

        return value.isoformat().replace("+00:00", "Z")


class DocumentSegmentRead(BaseModel):
    id: UUID
    parsed_document_id: UUID
    owner_user_id: UUID
    sequence_index: int
    segment_type: str
    page_no: int | None
    heading_path: list[str] | None
    text: str
    metadata: dict | None
    created_at: datetime

    @field_serializer("created_at")
    def serialize_datetime(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)

        return value.isoformat().replace("+00:00", "Z")


class DocumentSegmentPageRead(BaseModel):
    items: list[DocumentSegmentRead]
    total: int
    offset: int
    limit: int
