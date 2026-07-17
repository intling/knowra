"""create document_embedding_jobs and document_embeddings tables

Revision ID: 20260716_0001
Revises: 20260612_0001
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260716_0001"
down_revision: str | Sequence[str] | None = "20260612_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_embedding_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chunk_job_id", sa.Uuid(), nullable=False),
        sa.Column("parsed_document_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("embedder_name", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding_count", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(2048), nullable=True),
        sa.Column("config_json", postgresql.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["chunk_job_id"],
            ["document_chunk_jobs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["parsed_document_id"],
            ["parsed_documents.id"],
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
        ),
    )
    op.create_index(
        "ix_document_embedding_jobs_owner_user_id",
        "document_embedding_jobs",
        ["owner_user_id"],
    )
    op.create_index(
        "ix_document_embedding_jobs_chunk_job_id",
        "document_embedding_jobs",
        ["chunk_job_id"],
    )
    op.create_index(
        "ix_document_embedding_jobs_parsed_document_id",
        "document_embedding_jobs",
        ["parsed_document_id"],
    )
    op.create_index(
        "ix_document_embedding_jobs_status",
        "document_embedding_jobs",
        ["status"],
    )

    op.create_table(
        "document_embeddings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("embedding_job_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("parsed_document_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_index", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding_json", postgresql.JSON(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["embedding_job_id"],
            ["document_embedding_jobs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["document_chunks.id"],
        ),
        sa.ForeignKeyConstraint(
            ["parsed_document_id"],
            ["parsed_documents.id"],
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
        ),
    )
    op.create_index(
        "ix_document_embeddings_embedding_job_id",
        "document_embeddings",
        ["embedding_job_id"],
    )
    op.create_index(
        "ix_document_embeddings_chunk_id",
        "document_embeddings",
        ["chunk_id"],
    )
    op.create_index(
        "ix_document_embeddings_owner_user_id",
        "document_embeddings",
        ["owner_user_id"],
    )
    op.create_index(
        "ix_document_embeddings_parsed_doc_seq_idx",
        "document_embeddings",
        ["parsed_document_id", "sequence_index"],
    )


def downgrade() -> None:
    op.drop_table("document_embeddings")
    op.drop_table("document_embedding_jobs")
