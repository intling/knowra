from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlmodel import Field, SQLModel

from app.models.user import utc_now


class DocumentChunkJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class DocumentChunkJob(SQLModel, table=True):
    __tablename__ = "document_chunk_jobs"
    __table_args__ = (
        Index("ix_document_chunk_jobs_owner_user_id", "owner_user_id"),
        Index("ix_document_chunk_jobs_parsed_document_id", "parsed_document_id"),
        Index("ix_document_chunk_jobs_status", "status"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    parsed_document_id: UUID = Field(
        sa_column=Column(ForeignKey("parsed_documents.id"), nullable=False),
    )
    owner_user_id: UUID = Field(
        sa_column=Column(ForeignKey("users.id"), nullable=False),
    )
    status: str = Field(
        default=DocumentChunkJobStatus.QUEUED.value,
        sa_column=Column(String(32), nullable=False),
    )
    chunker_name: str = Field(
        default="docling_hybrid",
        sa_column=Column(String(64), nullable=False),
    )
    chunker_version: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    chunk_config_json: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    chunk_count: int = Field(default=0, sa_column=Column(Integer, nullable=False))
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


class DocumentChunk(SQLModel, table=True):
    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("ix_document_chunks_chunk_job_id", "chunk_job_id"),
        Index("ix_document_chunks_parsed_document_id", "parsed_document_id"),
        Index("ix_document_chunks_owner_user_id", "owner_user_id"),
        Index(
            "ix_document_chunks_parsed_document_id_sequence_index",
            "parsed_document_id",
            "sequence_index",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    chunk_job_id: UUID = Field(
        sa_column=Column(ForeignKey("document_chunk_jobs.id"), nullable=False),
    )
    parsed_document_id: UUID = Field(
        sa_column=Column(ForeignKey("parsed_documents.id"), nullable=False),
    )
    owner_user_id: UUID = Field(
        sa_column=Column(ForeignKey("users.id"), nullable=False),
    )
    sequence_index: int = Field(sa_column=Column(Integer, nullable=False))
    text: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    text_storage_key: str | None = Field(
        default=None,
        sa_column=Column(String(1024), nullable=True),
    )
    contextualized_text: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    contextualized_text_storage_key: str | None = Field(
        default=None,
        sa_column=Column(String(1024), nullable=True),
    )
    token_count: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    heading_path: list[str] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    page_numbers: list[int] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    chunk_type: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    source_segment_indices: list[int] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    metadata_json: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
