"""KBFingerprintService 单元测试 —— 知识库指纹计算。

测试覆盖：
- 空知识库指纹（无向量化数据时的稳定哈希）
- 有数据时的指纹变化（新增文档向量化后指纹应变化）
- 幂等性（同一数据状态多次计算应返回相同指纹）
"""

from __future__ import annotations

from datetime import UTC
from uuid import UUID

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.services.kb_fingerprint import compute_fingerprint

# 指纹按用户计算；既有用例统一使用同一测试用户。
OWNER_ID = UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def db_session() -> Session:
    """创建内存 SQLite 数据库会话（含所有表）。"""
    # 确保模型表已注册
    __import__("app.models.document_embedding")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


# ══════════════════════════════════════════════════════════
# 空知识库指纹测试
# ══════════════════════════════════════════════════════════


class TestEmptyKnowledgeBase:
    """验证空知识库（无已向量化数据）的指纹行为。"""

    def test_fingerprint_is_stable_for_empty_db(self, db_session):
        """空知识库的指纹应稳定（多次调用返回相同值）。"""
        fp1 = compute_fingerprint(db_session, owner_user_id=OWNER_ID)
        fp2 = compute_fingerprint(db_session, owner_user_id=OWNER_ID)
        assert fp1 == fp2
        assert len(fp1) == 16

    def test_fingerprint_has_expected_length(self, db_session):
        """指纹长度应为 16 字符。"""
        fp = compute_fingerprint(db_session, owner_user_id=OWNER_ID)
        assert len(fp) == 16

    def test_fingerprint_is_hex_string(self, db_session):
        """指纹应为十六进制字符串。"""
        fp = compute_fingerprint(db_session, owner_user_id=OWNER_ID)
        # 验证所有字符都是十六进制数字
        assert all(c in "0123456789abcdef" for c in fp)


# ══════════════════════════════════════════════════════════
# 指纹变化测试
# ══════════════════════════════════════════════════════════


class TestFingerprintChange:
    """验证知识库数据变化时指纹改变。"""

    # 验证完整可见资料链新增向量会改变该用户指纹；孤立无归属资料不计入可见范围。
    def test_fingerprint_changes_after_adding_document(self, db_session, tmp_path):
        from app.models.user import User
        from tests.auth_helpers import seed_knowledge_chain

        user = User(id=OWNER_ID, display_name="指纹测试用户")
        db_session.add(user)
        db_session.commit()
        fp_before = compute_fingerprint(db_session, owner_user_id=OWNER_ID)
        seed_knowledge_chain(db_session, tmp_path, user, vectors=1)
        fp_after = compute_fingerprint(db_session, owner_user_id=OWNER_ID)
        assert fp_before != fp_after

    def test_unsuccessful_jobs_do_not_affect_fingerprint(self, db_session):
        """状态非 succeeded 的向量化任务不影响指纹。"""
        from datetime import datetime
        from uuid import uuid4

        from app.models.document_embedding import DocumentEmbeddingJob

        fp_before = compute_fingerprint(db_session, owner_user_id=OWNER_ID)

        # 添加失败的任务
        job = DocumentEmbeddingJob(
            id=uuid4(),
            chunk_job_id=uuid4(),
            parsed_document_id=uuid4(),
            owner_user_id=OWNER_ID,
            status="failed",
            embedder_name="openai_compatible",
            model="test-model",
            dimensions=128,
            embedding_count=0,
            updated_at=datetime.now(UTC),
        )
        db_session.add(job)
        db_session.commit()

        fp_after = compute_fingerprint(db_session, owner_user_id=OWNER_ID)
        # 失败的任务不影响 MAX(updated_at) WHERE status='succeeded'
        # 但 COUNT 是通过 document_embeddings 表计算的，不受此影响
        # 所以失败任务不会改变指纹
        assert fp_before == fp_after

    def test_fingerprint_idempotent_for_same_state(self, db_session):
        """同一数据库状态多次计算应返回相同指纹。"""
        fp1 = compute_fingerprint(db_session, owner_user_id=OWNER_ID)
        fp2 = compute_fingerprint(db_session, owner_user_id=OWNER_ID)
        fp3 = compute_fingerprint(db_session, owner_user_id=OWNER_ID)
        assert fp1 == fp2 == fp3


# ══════════════════════════════════════════════════════════
# 指纹计算函数签名测试
# ══════════════════════════════════════════════════════════


class TestFingerprintReturnType:
    """验证 compute_fingerprint 的返回值类型。"""

    def test_returns_string(self, db_session):
        """compute_fingerprint 应返回 str 类型。"""
        fp = compute_fingerprint(db_session, owner_user_id=OWNER_ID)
        assert isinstance(fp, str)

    def test_no_whitespace_in_fingerprint(self, db_session):
        """指纹不应包含空白字符。"""
        fp = compute_fingerprint(db_session, owner_user_id=OWNER_ID)
        assert fp.strip() == fp
        assert " " not in fp
        assert "\n" not in fp
