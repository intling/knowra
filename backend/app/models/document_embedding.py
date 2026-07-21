from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String
from sqlmodel import Field, SQLModel

from app.models.user import utc_now


class DocumentEmbeddingJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class DocumentEmbeddingJob(SQLModel, table=True):
    __tablename__ = "document_embedding_jobs"
    __table_args__ = (
        Index("ix_document_embedding_jobs_owner_user_id", "owner_user_id"),
        Index("ix_document_embedding_jobs_chunk_job_id", "chunk_job_id"),
        Index("ix_document_embedding_jobs_parsed_document_id", "parsed_document_id"),
        Index("ix_document_embedding_jobs_status", "status"),
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
    status: str = Field(
        default=DocumentEmbeddingJobStatus.QUEUED.value,
        sa_column=Column(String(32), nullable=False),
    )
    embedder_name: str = Field(
        default="openai_compatible",
        sa_column=Column(String(64), nullable=False),
    )
    model: str = Field(
        sa_column=Column(String(128), nullable=False),
    )
    dimensions: int = Field(
        sa_column=Column(Integer, nullable=False),
    )
    embedding_count: int = Field(default=0, sa_column=Column(Integer, nullable=False))
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
    config_json: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class DocumentEmbedding(SQLModel, table=True):
    __tablename__ = "document_embeddings"
    __table_args__ = (
        Index("ix_document_embeddings_embedding_job_id", "embedding_job_id"),
        Index("ix_document_embeddings_chunk_id", "chunk_id"),
        Index("ix_document_embeddings_owner_user_id", "owner_user_id"),
        Index(
            "ix_document_embeddings_parsed_doc_seq_idx",
            "parsed_document_id",
            "sequence_index",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    embedding_job_id: UUID = Field(
        sa_column=Column(ForeignKey("document_embedding_jobs.id"), nullable=False),
    )
    chunk_id: UUID = Field(
        sa_column=Column(ForeignKey("document_chunks.id"), nullable=False),
    )
    parsed_document_id: UUID = Field(
        sa_column=Column(ForeignKey("parsed_documents.id"), nullable=False),
    )
    owner_user_id: UUID = Field(
        sa_column=Column(ForeignKey("users.id"), nullable=False),
    )
    sequence_index: int = Field(sa_column=Column(Integer, nullable=False))
    model: str = Field(
        sa_column=Column(String(128), nullable=False),
    )
    dimensions: int = Field(
        sa_column=Column(Integer, nullable=False),
    )
    embedding_json: list[float] = Field(
        sa_column=Column(JSON, nullable=False),
    )
    embedding_vector: list[float] = Field(
        sa_column=Column(Vector(2560), nullable=False),
    )
    token_count: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
