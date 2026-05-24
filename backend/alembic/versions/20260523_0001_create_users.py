"""create users table

Revision ID: 20260523_0001
Revises: 20260514_0001
Create Date: 2026-05-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260523_0001"
down_revision: str | Sequence[str] | None = "20260514_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("avatar_url", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_status_deleted_at", "users", ["status", "deleted_at"])
    op.execute(
        sa.text(
            """
            INSERT INTO users (id, display_name, status, created_at, updated_at)
            VALUES (:id, 'Default User', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        ).bindparams(id=DEFAULT_USER_ID)
    )


def downgrade() -> None:
    op.drop_index("ix_users_status_deleted_at", table_name="users")
    op.drop_table("users")
