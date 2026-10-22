"""增加模型配置与每种用途唯一绑定，不迁移或修改用户资料。"""

import sqlalchemy as sa

from alembic import op

revision = "20261022_0001"
down_revision = "20261021_0002"
branch_labels = None
depends_on = None
KINDS = ("chat", "embedding", "rerank", "query_rewrite")


def upgrade() -> None:
    op.create_table(
        "model_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("base_url", sa.String(2048), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("timeout_seconds", sa.Float(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=True),
        sa.Column("api_format", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('chat','embedding','rerank','query_rewrite')", name="ck_model_profiles_kind"
        ),
    )
    op.create_index("ix_model_profiles_kind", "model_profiles", ["kind"])
    bindings = op.create_table(
        "model_bindings",
        sa.Column("kind", sa.String(32), primary_key=True),
        sa.Column("profile_id", sa.Uuid(), sa.ForeignKey("model_profiles.id"), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('chat','embedding','rerank','query_rewrite')", name="ck_model_bindings_kind"
        ),
    )
    op.bulk_insert(bindings, [{"kind": kind, "profile_id": None, "revision": 0} for kind in KINDS])


def downgrade() -> None:
    op.drop_table("model_bindings")
    op.drop_index("ix_model_profiles_kind", table_name="model_profiles")
    op.drop_table("model_profiles")
