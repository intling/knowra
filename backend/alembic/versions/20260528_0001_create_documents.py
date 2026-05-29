"""create documents and document_chunks tables

Revision ID: 20260528_0001
Revises: 20260525_0001
Create Date: 2026-05-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260528_0001"
down_revision: str | Sequence[str] | None = "20260525_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_file_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("source_content_type", sa.String(length=255), nullable=True),
        sa.Column("parser_name", sa.String(length=100), nullable=True),
        sa.Column("parser_version", sa.String(length=100), nullable=True),
        sa.Column("chunker_name", sa.String(length=100), nullable=True),
        sa.Column("chunker_version", sa.String(length=100), nullable=True),
        sa.Column("tokenizer_name", sa.String(length=100), nullable=True),
        sa.Column("tokenizer_version", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("total_chars", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["uploaded_file_id"], ["uploaded_files.id"]),
    )
    op.create_unique_constraint(
        "uq_documents_uploaded_file_id",
        "documents",
        ["uploaded_file_id"],
    )
    op.create_index("ix_documents_owner_user_id", "documents", ["owner_user_id"])
    op.create_index("ix_documents_uploaded_file_id", "documents", ["uploaded_file_id"])
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_index("ix_documents_created_at", "documents", ["created_at"])

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("source_locator_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
    )
    op.create_unique_constraint(
        "uq_document_chunks_document_index",
        "document_chunks",
        ["document_id", "chunk_index"],
    )
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])
    op.create_index("ix_document_chunks_owner_user_id", "document_chunks", ["owner_user_id"])
    op.create_index(
        "ix_document_chunks_document_id_chunk_index",
        "document_chunks",
        ["document_id", "chunk_index"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_document_id_chunk_index", table_name="document_chunks")
    op.drop_index("ix_document_chunks_owner_user_id", table_name="document_chunks")
    op.drop_index("ix_document_chunks_document_id", table_name="document_chunks")
    op.drop_table("document_chunks")

    op.drop_index("ix_documents_created_at", table_name="documents")
    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_index("ix_documents_uploaded_file_id", table_name="documents")
    op.drop_index("ix_documents_owner_user_id", table_name="documents")
    op.drop_table("documents")
