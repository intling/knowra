from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel

from app.models.user import utc_now


class Document(SQLModel, table=True):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("uploaded_file_id", name="uq_documents_uploaded_file_id"),
        Index("ix_documents_owner_user_id", "owner_user_id"),
        Index("ix_documents_uploaded_file_id", "uploaded_file_id"),
        Index("ix_documents_status", "status"),
        Index("ix_documents_created_at", "created_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    owner_user_id: UUID = Field(
        sa_column=Column(ForeignKey("users.id"), nullable=False),
    )
    uploaded_file_id: UUID = Field(
        sa_column=Column(ForeignKey("uploaded_files.id"), nullable=False),
    )
    title: str = Field(sa_column=Column(String(255), nullable=False))
    source_content_type: str | None = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    parser_name: str | None = Field(default=None, sa_column=Column(String(100), nullable=True))
    parser_version: str | None = Field(default=None, sa_column=Column(String(100), nullable=True))
    chunker_name: str | None = Field(default=None, sa_column=Column(String(100), nullable=True))
    chunker_version: str | None = Field(default=None, sa_column=Column(String(100), nullable=True))
    tokenizer_name: str | None = Field(default=None, sa_column=Column(String(100), nullable=True))
    tokenizer_version: str | None = Field(
        default=None,
        sa_column=Column(String(100), nullable=True),
    )
    status: str = Field(default="parsed", sa_column=Column(String(32), nullable=False))
    chunk_count: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    total_chars: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    content_sha256: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    error_message: str | None = Field(default=None, sa_column=Column(String(1024), nullable=True))
    deleted_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
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
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_document_index"),
        Index("ix_document_chunks_document_id", "document_id"),
        Index("ix_document_chunks_owner_user_id", "owner_user_id"),
        Index("ix_document_chunks_document_id_chunk_index", "document_id", "chunk_index"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    document_id: UUID = Field(
        sa_column=Column(ForeignKey("documents.id"), nullable=False),
    )
    owner_user_id: UUID = Field(
        sa_column=Column(ForeignKey("users.id"), nullable=False),
    )
    chunk_index: int = Field(sa_column=Column(Integer, nullable=False))
    content: str = Field(sa_column=Column(Text, nullable=False))
    content_sha256: str = Field(sa_column=Column(String(64), nullable=False))
    char_start: int = Field(sa_column=Column(Integer, nullable=False))
    char_end: int = Field(sa_column=Column(Integer, nullable=False))
    token_count: int = Field(sa_column=Column(Integer, nullable=False))
    source_locator_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
