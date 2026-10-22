"""Add persistent account chat limits and usage reservations."""

import sqlalchemy as sa

from alembic import op

revision = "20261021_0002"
down_revision = "20261021_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_chat_limits",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("hourly_limit", sa.Integer(), nullable=False),
        sa.CheckConstraint("hourly_limit > 0", name="ck_user_chat_limits_positive"),
    )
    op.create_table(
        "chat_usage",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_usage_user_created", "chat_usage", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_chat_usage_user_created", table_name="chat_usage")
    op.drop_table("chat_usage")
    op.drop_table("user_chat_limits")
