"""知识库指纹服务 —— 用于缓存失效判定。

通过聚合 ``document_embeddings`` 行数与 ``document_embedding_jobs`` 的
最近成功时间生成轻量指纹（SHA-256[:16]）。当知识库文档发生变更（新增/重嵌）
后，指纹即发生变化，下游缓存可在惰性校验时将其检测为过期。

Usage::

    from app.services.kb_fingerprint import compute_fingerprint

    fp = compute_fingerprint(session)
    # 若无任何已向量化数据，返回 "0:None" 的稳定哈希
"""

from __future__ import annotations

import hashlib

from sqlmodel import Session, func, select

from app.core.logging import get_logger
from app.models.document_embedding import DocumentEmbedding, DocumentEmbeddingJob

logger = get_logger(__name__)


def compute_fingerprint(session: Session) -> str:
    """计算当前知识库的指纹字符串。

    基于以下数据聚合：
        - ``COUNT(*)`` from ``document_embeddings``（成功写入的向量数）
        - ``MAX(updated_at)`` from ``document_embedding_jobs``
          WHERE ``status = 'succeeded'``（最近一次成功向量化时间）

    指纹长度固定 16 字符（SHA-256 hex[:16]），可在 1ms 内完成查询。
    返回值为纯哈希无盐字符串，不包含原始聚合值。
    """
    count = session.exec(
        select(func.count()).select_from(DocumentEmbedding)
    ).one()

    max_updated = session.exec(
        select(func.max(DocumentEmbeddingJob.updated_at)).where(
            DocumentEmbeddingJob.status == "succeeded"
        )
    ).one()

    raw = f"{count}:{max_updated}"
    fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:16]

    logger.debug(
        "kb_fingerprint_computed",
        embedding_count=count,
        max_updated_at=str(max_updated),
        fingerprint=fingerprint,
    )
    return fingerprint
