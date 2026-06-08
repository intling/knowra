from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlmodel import Field, SQLModel

from app.models.user import utc_now


class DocumentParseJob(SQLModel, table=True):
    __tablename__ = "document_parse_jobs"
    __table_args__ = (
        Index("ix_document_parse_jobs_owner_user_id", "owner_user_id"),
        Index("ix_document_parse_jobs_uploaded_file_id", "uploaded_file_id"),
        Index("ix_document_parse_jobs_status", "status"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    uploaded_file_id: UUID = Field(
        sa_column=Column(ForeignKey("uploaded_files.id"), nullable=False),
    )
    owner_user_id: UUID = Field(
        sa_column=Column(ForeignKey("users.id"), nullable=False),
    )
    status: str = Field(default="queued", sa_column=Column(String(32), nullable=False))
    parser_name: str = Field(default="docling", sa_column=Column(String(64), nullable=False))
    parser_version: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    attempt_count: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    started_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    finished_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    error_code: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    error_message: str | None = Field(default=None, sa_column=Column(String(2048), nullable=True))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ParsedDocument(SQLModel, table=True):
    __tablename__ = "parsed_documents"
    __table_args__ = (
        Index("ix_parsed_documents_uploaded_file_id", "uploaded_file_id"),
        Index("ix_parsed_documents_parse_job_id", "parse_job_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    uploaded_file_id: UUID = Field(
        sa_column=Column(ForeignKey("uploaded_files.id"), nullable=False),
    )
    parse_job_id: UUID = Field(
        sa_column=Column(ForeignKey("document_parse_jobs.id"), nullable=False),
    )
    owner_user_id: UUID = Field(
        sa_column=Column(ForeignKey("users.id"), nullable=False),
    )
    source_checksum_sha256: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True),
    )
    markdown_storage_key: str = Field(sa_column=Column(String(1024), nullable=False))
    text_storage_key: str = Field(sa_column=Column(String(1024), nullable=False))
    docling_json_storage_key: str = Field(sa_column=Column(String(1024), nullable=False))
    title: str | None = Field(default=None, sa_column=Column(String(512), nullable=True))
    page_count: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    metadata_json: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class DocumentSegment(SQLModel, table=True):
    __tablename__ = "document_segments"
    __table_args__ = (
        Index("ix_document_segments_parsed_document_id", "parsed_document_id"),
        Index("ix_document_segments_owner_user_id", "owner_user_id"),
        Index("ix_document_segments_sequence_index", "sequence_index"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    parsed_document_id: UUID = Field(
        sa_column=Column(ForeignKey("parsed_documents.id"), nullable=False),
    )
    owner_user_id: UUID = Field(
        sa_column=Column(ForeignKey("users.id"), nullable=False),
    )
    sequence_index: int = Field(sa_column=Column(Integer, nullable=False))
    segment_type: str = Field(sa_column=Column(String(64), nullable=False))
    page_no: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    heading_path: list[str] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    text: str = Field(sa_column=Column(Text, nullable=False))
    metadata_json: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
