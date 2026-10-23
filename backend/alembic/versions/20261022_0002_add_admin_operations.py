"""增加后台审计、模型诊断历史及配置版本，保留既有业务记录。"""

import sqlalchemy as sa

from alembic import op

revision = "20261022_0002"
down_revision = "20261022_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_profiles",
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.create_table(
        "admin_audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("changes_json", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "result IN ('success', 'denied', 'failed')", name="ck_admin_audit_result"
        ),
    )
    op.create_index("ix_admin_audit_created_id", "admin_audit_events", ["created_at", "id"])
    op.create_index(
        "ix_admin_audit_actor_created", "admin_audit_events", ["actor_user_id", "created_at"]
    )
    op.create_index("ix_admin_audit_action_created", "admin_audit_events", ["action", "created_at"])
    op.create_index("ix_admin_audit_trace_id", "admin_audit_events", ["trace_id"])
    op.create_table(
        "model_probe_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "profile_id",
            sa.Uuid(),
            sa.ForeignKey("model_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("profile_revision", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("code", sa.String(64), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "status IN ('running', 'passed', 'failed', 'interrupted')",
            name="ck_model_probe_status",
        ),
    )
    op.create_index(
        "ix_model_probe_profile_started", "model_probe_results", ["profile_id", "started_at"]
    )
    op.create_index("ix_model_probe_lease_expires", "model_probe_results", ["lease_expires_at"])


def downgrade() -> None:
    op.drop_table("model_probe_results")
    op.drop_table("admin_audit_events")
    op.drop_column("model_profiles", "revision")
