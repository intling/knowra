"""replace ix_uploaded_files_dedup with partial unique index for soft-delete-aware dedup

Revision ID: 20260812_0002
Revises: 20260720_0001
Create Date: 2026-08-12
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "20260812_0002"
down_revision: str | Sequence[str] | None = "20260720_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 删除旧的普通复合索引 (owner_user_id, checksum_sha256, deleted_at)
    # 旧索引从未通过迁移脚本创建，仅存在于历史模型定义中，故使用 if_exists 兜底
    op.drop_index("ix_uploaded_files_dedup", table_name="uploaded_files", if_exists=True)

    # ── 数据去重：创建唯一索引前，先软删除历史遗留的重复活跃记录 ──────────
    # 历史数据中可能存在同一用户下 checksum 相同且均未软删除的多条记录，
    # 这会导致唯一索引创建失败。此处每个 (owner_user_id, checksum_sha256) 组
    # 只保留 id 最小的一条活跃记录，其余软删除（与 _soft_delete_duplicate 语义一致）。
    op.execute(
        text(
            """
            UPDATE uploaded_files AS uf
            SET deleted_at = now(),
                updated_at = now()
            WHERE uf.deleted_at IS NULL
              AND uf.checksum_sha256 IS NOT NULL
              AND EXISTS (
                  SELECT 1
                  FROM uploaded_files AS keep
                  WHERE keep.owner_user_id = uf.owner_user_id
                    AND keep.checksum_sha256 = uf.checksum_sha256
                    AND keep.deleted_at IS NULL
                    AND keep.id < uf.id
              )
            """
        )
    )

    # 创建 partial unique index：同一用户下，未软删除的记录 (owner_user_id, checksum_sha256) 必须唯一
    op.create_index(
        "ix_uploaded_files_dedup",
        "uploaded_files",
        ["owner_user_id", "checksum_sha256"],
        unique=True,
        postgresql_where=text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_uploaded_files_dedup", table_name="uploaded_files")
    op.create_index(
        "ix_uploaded_files_dedup",
        "uploaded_files",
        ["owner_user_id", "checksum_sha256", "deleted_at"],
        unique=False,
    )
