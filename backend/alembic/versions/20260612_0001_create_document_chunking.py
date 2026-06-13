"""create document chunking tables

Revision ID: 20260612_0001
Revises: 20260605_0001
Create Date: 2026-06-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260612_0001"
down_revision: str | Sequence[str] | None = "20260605_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CURRENT_DOCUMENT_CHUNKS_COLUMNS = {
    "chunk_job_id",
    "parsed_document_id",
    "sequence_index",
}
LEGACY_DOCUMENT_CHUNKS_TABLE = "legacy_document_chunks_20260612_0001"


def _archive_legacy_document_chunks_if_needed() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("document_chunks"):
        return

    column_names = {column["name"] for column in inspector.get_columns("document_chunks")}
    if column_names >= CURRENT_DOCUMENT_CHUNKS_COLUMNS:
        return

    # Older local prototypes used the same table name with a different schema.
    # Preserve that data under an explicit legacy name before creating the new table.
    op.drop_index(
        "ix_document_chunks_owner_user_id",
        table_name="document_chunks",
        if_exists=True,
    )
    op.rename_table("document_chunks", LEGACY_DOCUMENT_CHUNKS_TABLE)


def upgrade() -> None:
    _archive_legacy_document_chunks_if_needed()

    op.create_table(
        "document_chunk_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("parsed_document_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("chunker_name", sa.String(length=64), nullable=False),
        sa.Column("chunker_version", sa.String(length=64), nullable=True),
        sa.Column("chunk_config_json", sa.JSON(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=2048), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["parsed_document_id"], ["parsed_documents.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        if_not_exists=True,
    )
    op.create_index(
        "ix_document_chunk_jobs_owner_user_id",
        "document_chunk_jobs",
        ["owner_user_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_document_chunk_jobs_parsed_document_id",
        "document_chunk_jobs",
        ["parsed_document_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_document_chunk_jobs_status",
        "document_chunk_jobs",
        ["status"],
        if_not_exists=True,
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("chunk_job_id", sa.Uuid(), nullable=False),
        sa.Column("parsed_document_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("text_storage_key", sa.String(length=1024), nullable=True),
        sa.Column("contextualized_text", sa.Text(), nullable=True),
        sa.Column("contextualized_text_storage_key", sa.String(length=1024), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("heading_path", sa.JSON(), nullable=True),
        sa.Column("page_numbers", sa.JSON(), nullable=True),
        sa.Column("chunk_type", sa.String(length=64), nullable=True),
        sa.Column("source_segment_indices", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chunk_job_id"], ["document_chunk_jobs.id"]),
        sa.ForeignKeyConstraint(["parsed_document_id"], ["parsed_documents.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        if_not_exists=True,
    )
    op.create_index(
        "ix_document_chunks_chunk_job_id",
        "document_chunks",
        ["chunk_job_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_document_chunks_parsed_document_id",
        "document_chunks",
        ["parsed_document_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_document_chunks_owner_user_id",
        "document_chunks",
        ["owner_user_id"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_document_chunks_parsed_document_id_sequence_index",
        "document_chunks",
        ["parsed_document_id", "sequence_index"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_chunks_parsed_document_id_sequence_index",
        table_name="document_chunks",
        if_exists=True,
    )
    op.drop_index(
        "ix_document_chunks_owner_user_id",
        table_name="document_chunks",
        if_exists=True,
    )
    op.drop_index(
        "ix_document_chunks_parsed_document_id",
        table_name="document_chunks",
        if_exists=True,
    )
    op.drop_index(
        "ix_document_chunks_chunk_job_id",
        table_name="document_chunks",
        if_exists=True,
    )
    op.drop_table("document_chunks", if_exists=True)

    op.drop_index(
        "ix_document_chunk_jobs_status",
        table_name="document_chunk_jobs",
        if_exists=True,
    )
    op.drop_index(
        "ix_document_chunk_jobs_parsed_document_id",
        table_name="document_chunk_jobs",
        if_exists=True,
    )
    op.drop_index(
        "ix_document_chunk_jobs_owner_user_id",
        table_name="document_chunk_jobs",
        if_exists=True,
    )
    op.drop_table("document_chunk_jobs", if_exists=True)
