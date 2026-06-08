"""create document parsing tables

Revision ID: 20260605_0001
Revises: 20260525_0001
Create Date: 2026-06-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260605_0001"
down_revision: str | Sequence[str] | None = "20260525_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_parse_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("uploaded_file_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("parser_name", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=2048), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["uploaded_file_id"], ["uploaded_files.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
    )
    op.create_index(
        "ix_document_parse_jobs_owner_user_id",
        "document_parse_jobs",
        ["owner_user_id"],
    )
    op.create_index(
        "ix_document_parse_jobs_uploaded_file_id",
        "document_parse_jobs",
        ["uploaded_file_id"],
    )
    op.create_index("ix_document_parse_jobs_status", "document_parse_jobs", ["status"])

    op.create_table(
        "parsed_documents",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("uploaded_file_id", sa.Uuid(), nullable=False),
        sa.Column("parse_job_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("source_checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("markdown_storage_key", sa.String(length=1024), nullable=False),
        sa.Column("text_storage_key", sa.String(length=1024), nullable=False),
        sa.Column("docling_json_storage_key", sa.String(length=1024), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["uploaded_file_id"], ["uploaded_files.id"]),
        sa.ForeignKeyConstraint(["parse_job_id"], ["document_parse_jobs.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
    )
    op.create_index(
        "ix_parsed_documents_uploaded_file_id",
        "parsed_documents",
        ["uploaded_file_id"],
    )
    op.create_index("ix_parsed_documents_parse_job_id", "parsed_documents", ["parse_job_id"])

    op.create_table(
        "document_segments",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("parsed_document_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_index", sa.Integer(), nullable=False),
        sa.Column("segment_type", sa.String(length=64), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=True),
        sa.Column("heading_path", sa.JSON(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["parsed_document_id"], ["parsed_documents.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
    )
    op.create_index(
        "ix_document_segments_parsed_document_id",
        "document_segments",
        ["parsed_document_id"],
    )
    op.create_index(
        "ix_document_segments_owner_user_id",
        "document_segments",
        ["owner_user_id"],
    )
    op.create_index(
        "ix_document_segments_sequence_index",
        "document_segments",
        ["sequence_index"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_segments_sequence_index", table_name="document_segments")
    op.drop_index("ix_document_segments_owner_user_id", table_name="document_segments")
    op.drop_index("ix_document_segments_parsed_document_id", table_name="document_segments")
    op.drop_table("document_segments")

    op.drop_index("ix_parsed_documents_parse_job_id", table_name="parsed_documents")
    op.drop_index("ix_parsed_documents_uploaded_file_id", table_name="parsed_documents")
    op.drop_table("parsed_documents")

    op.drop_index("ix_document_parse_jobs_status", table_name="document_parse_jobs")
    op.drop_index("ix_document_parse_jobs_uploaded_file_id", table_name="document_parse_jobs")
    op.drop_index("ix_document_parse_jobs_owner_user_id", table_name="document_parse_jobs")
    op.drop_table("document_parse_jobs")
