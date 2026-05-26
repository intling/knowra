"""create uploaded_files table

Revision ID: 20260525_0001
Revises: 20260523_0001
Create Date: 2026-05-25
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260525_0001"
down_revision: str | Sequence[str] | None = "20260523_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "uploaded_files",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False, unique=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
    )
    op.create_index(
        "ix_uploaded_files_owner_user_id",
        "uploaded_files",
        ["owner_user_id"],
    )
    op.create_index("ix_uploaded_files_status", "uploaded_files", ["status"])
    op.create_index("ix_uploaded_files_created_at", "uploaded_files", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_uploaded_files_created_at", table_name="uploaded_files")
    op.drop_index("ix_uploaded_files_status", table_name="uploaded_files")
    op.drop_index("ix_uploaded_files_owner_user_id", table_name="uploaded_files")
    op.drop_table("uploaded_files")
