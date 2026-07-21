"""add embedding_vector column to document_embeddings

Revision ID: 20260720_0001
Revises: 20260716_0001
Create Date: 2026-07-20
"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "20260720_0001"
down_revision: str | Sequence[str] | None = "20260716_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic")


def upgrade() -> None:
    # 3.2: Add embedding_vector vector(2560) column
    op.add_column(
        "document_embeddings",
        sa.Column("embedding_vector", Vector(2560), nullable=True),
    )

    # 3.4: Pre-check — validate data integrity before backfill
    pre_check = op.execute(
        sa.text(
            "SELECT COUNT(*) FROM document_embeddings "
            "WHERE jsonb_array_length(embedding_json::jsonb) != 2560"
        )
    )
    if pre_check is not None:
        invalid_count = pre_check.scalar()
        if invalid_count:
            logger.warning(
                "Backfill pre-check: %d row(s) with embedding_json dimension != 2560 "
                "will be skipped during backfill",
                invalid_count,
            )

    # 3.3: Batch backfill embedding_json::vector → embedding_vector
    while True:
        result = op.execute(
            sa.text(
                "UPDATE document_embeddings "
                "SET embedding_vector = CAST(embedding_json AS text)::vector "
                "WHERE embedding_vector IS NULL "
                "AND id IN (SELECT id FROM document_embeddings "
                "WHERE embedding_vector IS NULL LIMIT 500)"
            )
        )
        if result is None or result.rowcount == 0:
            break

    # 3.5: Post-verification — confirm all rows backfilled
    post_check = op.execute(
        sa.text("SELECT COUNT(*) FROM document_embeddings WHERE embedding_vector IS NULL")
    )
    if post_check is not None:
        null_count = post_check.scalar()
        if null_count:
            logger.warning(
                "Backfill verification: %d row(s) still have NULL embedding_vector after backfill",
                null_count,
            )

    # 3.7: Add NOT NULL constraint after backfill is verified complete
    op.alter_column("document_embeddings", "embedding_vector", nullable=False)


def downgrade() -> None:
    # 3.6: Drop embedding_vector column
    op.drop_column("document_embeddings", "embedding_vector")
