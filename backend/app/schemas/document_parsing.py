from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import UtcDateTime


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
    started_at: UtcDateTime | None
    finished_at: UtcDateTime | None
    error_code: str | None
    error_message: str | None
    created_at: UtcDateTime
    updated_at: UtcDateTime


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
    created_at: UtcDateTime


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
    created_at: UtcDateTime


class DocumentSegmentPageRead(BaseModel):
    items: list[DocumentSegmentRead]
    total: int
    offset: int
    limit: int
