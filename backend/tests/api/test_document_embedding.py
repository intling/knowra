# 本文件验证文档向量化 HTTP API 的用户可见行为。
# 覆盖向量化作业查询、向量结果查询、重新向量化创建/冲突、
# shutdown 拒绝、后台执行器生命周期、活跃结果取代和跨用户隔离。

from collections.abc import Generator
from contextlib import suppress
from datetime import UTC, datetime
from importlib import import_module
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import get_settings
from app.db.session import get_session
from app.main import app
from app.models.user import User
from app.services.users import DEFAULT_USER_ID
from tests.document_chunking_helpers import make_parsed_document_with_segment
from tests.document_parsing_helpers import make_user

# ── 响应字段集合（用于断言响应结构完整性）──────────────────────────

EMBEDDING_JOB_RESPONSE_FIELDS = {
    "id",
    "chunk_job_id",
    "parsed_document_id",
    "owner_user_id",
    "status",
    "embedder_name",
    "model",
    "dimensions",
    "embedding_count",
    "attempt_count",
    "started_at",
    "finished_at",
    "error_code",
    "error_message",
    "config_json",
    "created_at",
    "updated_at",
}

EMBEDDING_RESPONSE_FIELDS = {
    "id",
    "chunk_id",
    "embedding_job_id",
    "sequence_index",
    "model",
    "dimensions",
    "embedding_json",
    "token_count",
    "created_at",
}

EMBEDDING_PAGE_RESPONSE_FIELDS = {"items", "total", "offset", "limit"}


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def session() -> Generator[Session]:
    """提供 API 测试专用内存数据库，注册上传、解析、分块和向量化模型。"""
    import_module("app.models.uploaded_file")
    import_module("app.models.document_parsing")
    with suppress(ModuleNotFoundError):
        import_module("app.models.document_chunking")
    with suppress(ModuleNotFoundError):
        import_module("app.models.document_embedding")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as test_session:
        yield test_session


@pytest.fixture
def embedding_client(monkeypatch, session: Session, tmp_path) -> Generator[TestClient]:
    """将 FastAPI 依赖替换为测试 session，隔离本地存储副作用。"""
    monkeypatch.setenv("UPLOAD_STORAGE_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("DOCUMENT_CHUNK_ARTIFACT_STORAGE_DIR", str(tmp_path / "chunks"))
    get_settings.cache_clear()

    def override_get_session() -> Generator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    get_settings.cache_clear()


# ── Helpers ───────────────────────────────────────────────────────────


def seed_current_user(session: Session) -> User:
    """种下 API 认证层默认会解析到的当前用户。"""
    created_at = datetime(2026, 6, 12, tzinfo=UTC)
    user = User(
        id=DEFAULT_USER_ID,
        display_name="Default User",
        status="active",
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def make_shutdown_state():
    """创建 is_shutting_down=True 的 shutdown 状态对象。"""
    return SimpleNamespace(
        is_shutting_down=True,
        reason="signal",
    )


def _embedding_module():
    return import_module("app.models.document_embedding")


def _chunking_module():
    return import_module("app.models.document_chunking")


def _make_embedding_vector(dimensions: int = 2560) -> list[float]:
    """生成固定测试向量。"""
    return [0.1] * dimensions


def seed_successful_embedding_job(session: Session, tmp_path):
    """种下完整的成功向量化链路：用户 → 上传 → 解析 → 分块 → 向量化作业 → 向量结果。

    Returns:
        (user, parsed_document, chunk_job, embedding_job, chunks, embeddings)
    """
    emb_models = _embedding_module()
    chunk_models = _chunking_module()

    user = seed_current_user(session)
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )

    # 创建成功的分块作业
    chunk_job = chunk_models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="succeeded",
        chunker_name="docling_hybrid",
        chunker_version="docling-core",
        chunk_config_json={"max_tokens": 512},
        chunk_count=2,
    )
    session.add(chunk_job)
    session.commit()
    session.refresh(chunk_job)

    # 创建两个 chunk（故意按 sequence_index 乱序插入以验证排序）
    chunks = []
    for idx in [1, 0]:
        chunk = chunk_models.DocumentChunk(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed.id,
            owner_user_id=user.id,
            sequence_index=idx,
            text=f"Chunk {idx}",
            contextualized_text=f"Course Notes\nChunk {idx}",
            token_count=10 + idx,
            heading_path=["Course Notes"],
            page_numbers=[1],
            chunk_type="text",
            source_segment_indices=[0],
            metadata_json={"docling_ref": f"#/texts/{idx}"},
        )
        session.add(chunk)
        chunks.append(chunk)
    session.commit()
    for c in chunks:
        session.refresh(c)
    # 按 sequence_index 排序
    chunks.sort(key=lambda c: c.sequence_index)

    # 创建成功的向量化作业
    embedding_job = emb_models.DocumentEmbeddingJob(
        chunk_job_id=chunk_job.id,
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="succeeded",
        embedder_name="openai_compatible",
        model="Qwen/Qwen3-Embedding-4B",
        dimensions=2560,
        embedding_count=2,
        config_json={
            "model": "Qwen/Qwen3-Embedding-4B",
            "dimensions": 2560,
            "batch_size": 100,
            "encoding_format": "float",
        },
    )
    session.add(embedding_job)
    session.commit()
    session.refresh(embedding_job)

    # 创建向量结果
    embeddings = []
    embedding_vector = _make_embedding_vector()
    for chunk in chunks:
        emb = emb_models.DocumentEmbedding(
            embedding_job_id=embedding_job.id,
            chunk_id=chunk.id,
            parsed_document_id=parsed.id,
            owner_user_id=user.id,
            sequence_index=chunk.sequence_index,
            model="Qwen/Qwen3-Embedding-4B",
            dimensions=2560,
            embedding_json=embedding_vector,
            embedding_vector=embedding_vector,
            token_count=None,
        )
        session.add(emb)
        embeddings.append(emb)
    session.commit()
    for e in embeddings:
        session.refresh(e)

    return user, parsed, chunk_job, embedding_job, chunks, embeddings


def seed_embedding_job_with_status(
    session: Session,
    tmp_path,
    *,
    status: str,
    embedding_count: int = 0,
) -> tuple:
    """种下指定状态的向量化作业及其上游链路。"""
    emb_models = _embedding_module()
    chunk_models = _chunking_module()

    user = seed_current_user(session)
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )

    chunk_job = chunk_models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="succeeded",
        chunker_name="docling_hybrid",
        chunk_config_json={},
        chunk_count=0,
    )
    session.add(chunk_job)
    session.commit()
    session.refresh(chunk_job)

    embedding_job = emb_models.DocumentEmbeddingJob(
        chunk_job_id=chunk_job.id,
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status=status,
        embedder_name="openai_compatible",
        model="Qwen/Qwen3-Embedding-4B",
        dimensions=2560,
        embedding_count=embedding_count,
        config_json={"model": "Qwen/Qwen3-Embedding-4B", "dimensions": 2560},
    )
    session.add(embedding_job)
    session.commit()
    session.refresh(embedding_job)

    return user, parsed, chunk_job, embedding_job


# ═══════════════════════════════════════════════════════════════════════
# 8.1  GET /api/document-embedding-jobs/{id} — 返回 200 和正确数据结构
# ═══════════════════════════════════════════════════════════════════════


def test_get_embedding_job_returns_owned_job(
    embedding_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """作业详情接口应允许当前用户读取自己的向量化作业。"""
    _user, _parsed, _chunk_job, embedding_job, _chunks, _embeddings = seed_successful_embedding_job(
        session, tmp_path
    )

    response = embedding_client.get(f"/api/document-embedding-jobs/{embedding_job.id}")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == EMBEDDING_JOB_RESPONSE_FIELDS
    assert payload["id"] == str(embedding_job.id)
    assert payload["status"] == "succeeded"
    assert payload["model"] == "Qwen/Qwen3-Embedding-4B"
    assert payload["dimensions"] == 2560
    assert payload["embedding_count"] == 2
    assert payload["config_json"] == {
        "model": "Qwen/Qwen3-Embedding-4B",
        "dimensions": 2560,
        "batch_size": 100,
        "encoding_format": "float",
    }


def test_get_embedding_job_returns_404_when_not_found(
    embedding_client: TestClient,
    session: Session,
) -> None:
    """不存在的作业 ID 应返回 404。"""
    seed_current_user(session)

    response = embedding_client.get(
        "/api/document-embedding-jobs/00000000-0000-0000-0000-000000000099"
    )

    assert response.status_code == 404


# ═══════════════════════════════════════════════════════════════════════
# 8.1a  GET /api/document-chunk-jobs/{id}/embedding-job — 返回最新向量化作业
# ═══════════════════════════════════════════════════════════════════════


def test_get_chunk_job_latest_embedding_job_returns_job(
    embedding_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """应返回分块作业最新的向量化作业（不限状态）。"""
    user, parsed, chunk_job, embedding_job = seed_embedding_job_with_status(
        session, tmp_path, status="failed", embedding_count=0
    )

    response = embedding_client.get(f"/api/document-chunk-jobs/{chunk_job.id}/embedding-job")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == EMBEDDING_JOB_RESPONSE_FIELDS
    assert payload["id"] == str(embedding_job.id)
    assert payload["status"] == "failed"


def test_get_chunk_job_latest_embedding_job_returns_404_when_no_job(
    embedding_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """当分块作业没有向量化作业记录时应返回 404。"""
    user = seed_current_user(session)
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )
    chunk_models = _chunking_module()
    chunk_job = chunk_models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="succeeded",
        chunker_name="docling_hybrid",
        chunk_config_json={},
    )
    session.add(chunk_job)
    session.commit()
    session.refresh(chunk_job)

    response = embedding_client.get(f"/api/document-chunk-jobs/{chunk_job.id}/embedding-job")

    assert response.status_code == 404
    assert "No embedding job found" in response.text


def test_get_chunk_job_latest_embedding_job_returns_404_when_chunk_job_not_found(
    embedding_client: TestClient,
    session: Session,
) -> None:
    """不存在的分块作业 ID 应返回 404。"""
    seed_current_user(session)

    response = embedding_client.get(
        "/api/document-chunk-jobs/00000000-0000-0000-0000-000000000099/embedding-job"
    )

    assert response.status_code == 404


def test_get_chunk_job_latest_embedding_job_rejects_foreign_chunk_job(
    embedding_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """查询其他用户分块作业的向量化作业应返回 404。"""
    seed_current_user(session)
    other_user = make_user(session, display_name="Other User")
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=other_user,
    )
    chunk_models = _chunking_module()
    foreign_chunk_job = chunk_models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=other_user.id,
        status="succeeded",
        chunker_name="docling_hybrid",
        chunk_config_json={},
    )
    session.add(foreign_chunk_job)
    session.commit()

    response = embedding_client.get(
        f"/api/document-chunk-jobs/{foreign_chunk_job.id}/embedding-job"
    )

    assert response.status_code == 404


# ═══════════════════════════════════════════════════════════════════════
# 8.2  GET /api/document-embedding-jobs/{id} — 跨用户隔离
# ═══════════════════════════════════════════════════════════════════════


def test_get_embedding_job_rejects_foreign_job(
    embedding_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """查询其他用户的向量化作业应返回非 2xx，且不泄露失败原因。"""
    emb_models = _embedding_module()
    chunk_models = _chunking_module()

    seed_current_user(session)
    other_user = make_user(session, display_name="Other User")
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=other_user,
    )

    chunk_job = chunk_models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=other_user.id,
        status="succeeded",
        chunker_name="docling_hybrid",
        chunk_config_json={},
    )
    session.add(chunk_job)
    session.commit()
    session.refresh(chunk_job)

    foreign_job = emb_models.DocumentEmbeddingJob(
        chunk_job_id=chunk_job.id,
        parsed_document_id=parsed.id,
        owner_user_id=other_user.id,
        status="failed",
        embedder_name="openai_compatible",
        model="test-model",
        dimensions=2560,
        error_code="api_error",
        error_message="private failure details",
        config_json={},
    )
    session.add(foreign_job)
    session.commit()

    response = embedding_client.get(f"/api/document-embedding-jobs/{foreign_job.id}")

    assert response.status_code == 404
    assert "private failure details" not in response.text


# ═══════════════════════════════════════════════════════════════════════
# 8.3  GET /api/document-chunk-jobs/{id}/embeddings — 分页 + 排序
# ═══════════════════════════════════════════════════════════════════════


def test_get_chunk_job_embeddings_returns_paginated_sorted(
    embedding_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """分块作业的向量列表应返回最新活跃作业的结果，按 sequence_index 排序。"""
    _user, _parsed, chunk_job, _embedding_job, chunks, _embeddings = seed_successful_embedding_job(
        session, tmp_path
    )

    response = embedding_client.get(
        f"/api/document-chunk-jobs/{chunk_job.id}/embeddings?offset=0&limit=10"
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == EMBEDDING_PAGE_RESPONSE_FIELDS
    assert payload["total"] == 2
    assert payload["offset"] == 0
    assert payload["limit"] == 10
    items = payload["items"]
    assert len(items) == 2
    # 按 sequence_index 排序
    assert [item["sequence_index"] for item in items] == [0, 1]
    # 每个 item 包含完整字段
    assert set(items[0]) == EMBEDDING_RESPONSE_FIELDS


def test_get_chunk_job_embeddings_returns_empty_when_no_active_job(
    embedding_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """当分块作业没有活跃向量化结果时，返回空分页而不是 404。"""
    user = seed_current_user(session)
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )
    chunk_models = _chunking_module()
    chunk_job = chunk_models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="succeeded",
        chunker_name="docling_hybrid",
        chunk_config_json={},
    )
    session.add(chunk_job)
    session.commit()
    session.refresh(chunk_job)

    response = embedding_client.get(f"/api/document-chunk-jobs/{chunk_job.id}/embeddings")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "offset": 0, "limit": 50}


def test_get_chunk_job_embeddings_uses_only_active_job(
    embedding_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """当存在 superseded 作业时，向量列表应使用最新的 succeeded 作业结果。"""
    emb_models = _embedding_module()

    user, parsed, chunk_job, embedding_job, chunks, embeddings = seed_successful_embedding_job(
        session, tmp_path
    )

    # 将原作业标记为 superseded
    embedding_job.status = "superseded"
    session.add(embedding_job)
    session.commit()

    # 创建新的 succeeded 作业（使用与列定义一致的 2560 维）
    new_job = emb_models.DocumentEmbeddingJob(
        chunk_job_id=chunk_job.id,
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="succeeded",
        embedder_name="openai_compatible",
        model="newer-model",
        dimensions=2560,
        embedding_count=2,
        config_json={"model": "newer-model", "dimensions": 2560},
    )
    session.add(new_job)
    session.commit()
    session.refresh(new_job)

    for chunk in chunks:
        session.add(
            emb_models.DocumentEmbedding(
                embedding_job_id=new_job.id,
                chunk_id=chunk.id,
                parsed_document_id=parsed.id,
                owner_user_id=user.id,
                sequence_index=chunk.sequence_index,
                model="newer-model",
                dimensions=2560,
                embedding_json=[0.2] * 2560,
                embedding_vector=[0.2] * 2560,
            )
        )
    session.commit()

    response = embedding_client.get(f"/api/document-chunk-jobs/{chunk_job.id}/embeddings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    # 应返回新模型的结果
    assert payload["items"][0]["model"] == "newer-model"
    assert payload["items"][0]["dimensions"] == 2560


# ═══════════════════════════════════════════════════════════════════════
# 8.4  GET /api/document-chunks/{id}/embedding — 单条向量详情
# ═══════════════════════════════════════════════════════════════════════


def test_get_chunk_embedding_returns_detail(
    embedding_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """chunk 的向量详情应返回完整字段和向量数组。"""
    _user, _parsed, _chunk_job, _embedding_job, chunks, embeddings = seed_successful_embedding_job(
        session, tmp_path
    )
    chunk_0 = chunks[0]  # sequence_index=0

    response = embedding_client.get(f"/api/document-chunks/{chunk_0.id}/embedding")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == EMBEDDING_RESPONSE_FIELDS
    assert payload["chunk_id"] == str(chunk_0.id)
    assert payload["sequence_index"] == 0
    assert payload["model"] == "Qwen/Qwen3-Embedding-4B"
    assert payload["dimensions"] == 2560
    assert len(payload["embedding_json"]) == 2560


def test_get_chunk_embedding_returns_404_when_chunk_not_found(
    embedding_client: TestClient,
    session: Session,
) -> None:
    """不存在的 chunk ID 应返回 404。"""
    seed_current_user(session)

    response = embedding_client.get(
        "/api/document-chunks/00000000-0000-0000-0000-000000000099/embedding"
    )

    assert response.status_code == 404


def test_get_chunk_embedding_returns_404_when_chunk_belongs_to_other_user(
    embedding_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """查询其他用户 chunk 的向量应返回 404，不泄露是否存在。"""
    chunk_models = _chunking_module()

    seed_current_user(session)
    other_user = make_user(session, display_name="Other User")
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=other_user,
    )
    foreign_chunk = chunk_models.DocumentChunk(
        chunk_job_id=parsed.id,  # 用 parsed.id 占位（chunk_job 实际存在即可）
        parsed_document_id=parsed.id,
        owner_user_id=other_user.id,
        sequence_index=0,
        text="Other user's chunk",
        chunk_type="text",
        source_segment_indices=[0],
    )
    # 需要真实的 chunk_job
    chunk_job = chunk_models.DocumentChunkJob(
        id=parsed.id,
        parsed_document_id=parsed.id,
        owner_user_id=other_user.id,
        status="succeeded",
        chunker_name="docling_hybrid",
        chunk_config_json={},
    )
    session.add(chunk_job)
    session.add(foreign_chunk)
    session.commit()

    response = embedding_client.get(f"/api/document-chunks/{foreign_chunk.id}/embedding")

    assert response.status_code == 404


def test_get_chunk_embedding_returns_404_when_no_active_embedding(
    embedding_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """当 chunk 存在但没有活跃向量结果时应返回 404。"""
    user = seed_current_user(session)
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )
    chunk_models = _chunking_module()
    chunk_job = chunk_models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="succeeded",
        chunker_name="docling_hybrid",
        chunk_config_json={},
    )
    session.add(chunk_job)
    session.commit()
    session.refresh(chunk_job)

    chunk = chunk_models.DocumentChunk(
        chunk_job_id=chunk_job.id,
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        sequence_index=0,
        text="Chunk without embedding",
        chunk_type="text",
        source_segment_indices=[0],
    )
    session.add(chunk)
    session.commit()
    session.refresh(chunk)

    response = embedding_client.get(f"/api/document-chunks/{chunk.id}/embedding")

    assert response.status_code == 404


# ═══════════════════════════════════════════════════════════════════════
# 8.5  POST /api/document-chunk-jobs/{id}/re-embed — 返回 202
# ═══════════════════════════════════════════════════════════════════════


def test_reembed_returns_202_and_created_job(
    embedding_client: TestClient,
    session: Session,
    tmp_path,
    monkeypatch,
) -> None:
    """重新向量化应创建 queued 作业并返回 202。

    后台执行器行为由 8.8–8.11 独立验证，此处仅断言 API 同步响应。
    为避免后台任务通过 ``default_session_factory`` 触达真实数据库，
    临时将 ``ReembedDispatcher.enqueue`` 替换为 no-op。
    """
    # 抑制后台任务执行（后台逻辑由独立测试覆盖）
    routes_mod = import_module("app.api.routes.document_embedding")
    monkeypatch.setattr(routes_mod.ReembedDispatcher, "enqueue", lambda self, job_id: None)

    user = seed_current_user(session)
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )
    chunk_models = _chunking_module()
    chunk_job = chunk_models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="succeeded",
        chunker_name="docling_hybrid",
        chunk_config_json={},
    )
    session.add(chunk_job)
    session.commit()
    session.refresh(chunk_job)

    response = embedding_client.post(
        f"/api/document-chunk-jobs/{chunk_job.id}/re-embed",
        json={"model": "Qwen/Qwen3-Embedding-4B", "dimensions": 2560},
    )

    assert response.status_code == 202
    payload = response.json()
    assert set(payload) == EMBEDDING_JOB_RESPONSE_FIELDS
    assert payload["chunk_job_id"] == str(chunk_job.id)
    assert payload["status"] == "queued"
    assert payload["model"] == "Qwen/Qwen3-Embedding-4B"
    assert payload["dimensions"] == 2560


def test_reembed_uses_default_model_when_not_specified(
    embedding_client: TestClient,
    session: Session,
    tmp_path,
    monkeypatch,
) -> None:
    """不指定 model/dimensions 时应使用配置默认值。

    后台执行器行为由 8.8–8.11 独立验证，此处仅断言 API 同步响应。
    """
    routes_mod = import_module("app.api.routes.document_embedding")
    monkeypatch.setattr(routes_mod.ReembedDispatcher, "enqueue", lambda self, job_id: None)

    user = seed_current_user(session)
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )
    chunk_models = _chunking_module()
    chunk_job = chunk_models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="succeeded",
        chunker_name="docling_hybrid",
        chunk_config_json={},
    )
    session.add(chunk_job)
    session.commit()
    session.refresh(chunk_job)

    response = embedding_client.post(
        f"/api/document-chunk-jobs/{chunk_job.id}/re-embed",
    )

    assert response.status_code == 202
    payload = response.json()
    # 使用默认配置值
    assert payload["model"] == "Qwen/Qwen3-Embedding-4B"
    assert payload["dimensions"] == 2560


def test_reembed_returns_404_when_chunk_job_not_found(
    embedding_client: TestClient,
    session: Session,
) -> None:
    """不存在的分块作业 ID 应返回 404。"""
    seed_current_user(session)

    response = embedding_client.post(
        "/api/document-chunk-jobs/00000000-0000-0000-0000-000000000099/re-embed",
    )

    assert response.status_code == 404


def test_reembed_returns_404_when_chunk_job_belongs_to_other_user(
    embedding_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """对其他用户的分块作业触发重新向量化应返回 404。"""
    seed_current_user(session)
    other_user = make_user(session, display_name="Other User")
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=other_user,
    )
    chunk_models = _chunking_module()
    foreign_chunk_job = chunk_models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=other_user.id,
        status="succeeded",
        chunker_name="docling_hybrid",
        chunk_config_json={},
    )
    session.add(foreign_chunk_job)
    session.commit()

    response = embedding_client.post(
        f"/api/document-chunk-jobs/{foreign_chunk_job.id}/re-embed",
    )

    assert response.status_code == 404


# ═══════════════════════════════════════════════════════════════════════
# 8.6  POST re-embed — 存在运行中作业时返回 409
# ═══════════════════════════════════════════════════════════════════════


def test_reembed_returns_409_when_job_is_already_running(
    embedding_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """同一分块作业已有 queued 或 running 向量化作业时应返回 409。"""
    emb_models = _embedding_module()

    user = seed_current_user(session)
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )
    chunk_models = _chunking_module()
    chunk_job = chunk_models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="succeeded",
        chunker_name="docling_hybrid",
        chunk_config_json={},
    )
    session.add(chunk_job)
    session.commit()
    session.refresh(chunk_job)

    # 创建一个 running 的向量化作业
    running_job = emb_models.DocumentEmbeddingJob(
        chunk_job_id=chunk_job.id,
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="running",
        embedder_name="openai_compatible",
        model="Qwen/Qwen3-Embedding-4B",
        dimensions=2560,
        config_json={},
    )
    session.add(running_job)
    session.commit()
    session.refresh(running_job)

    response = embedding_client.post(
        f"/api/document-chunk-jobs/{chunk_job.id}/re-embed",
    )

    assert response.status_code == 409
    payload = response.json()
    assert payload["detail"] == "Embedding job already running"
    assert payload["job"]["id"] == str(running_job.id)
    assert payload["job"]["status"] == "running"


def test_reembed_returns_409_when_job_is_queued(
    embedding_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """同一分块作业已有 queued 向量化作业时也应返回 409。"""
    emb_models = _embedding_module()

    user = seed_current_user(session)
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )
    chunk_models = _chunking_module()
    chunk_job = chunk_models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="succeeded",
        chunker_name="docling_hybrid",
        chunk_config_json={},
    )
    session.add(chunk_job)
    session.commit()
    session.refresh(chunk_job)

    queued_job = emb_models.DocumentEmbeddingJob(
        chunk_job_id=chunk_job.id,
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="queued",
        embedder_name="openai_compatible",
        model="Qwen/Qwen3-Embedding-4B",
        dimensions=2560,
        config_json={},
    )
    session.add(queued_job)
    session.commit()
    session.refresh(queued_job)

    response = embedding_client.post(
        f"/api/document-chunk-jobs/{chunk_job.id}/re-embed",
    )

    assert response.status_code == 409


# ═══════════════════════════════════════════════════════════════════════
# 8.7  POST re-embed — shutdown 期间返回 503
# ═══════════════════════════════════════════════════════════════════════


def test_reembed_returns_503_when_application_is_shutting_down(
    embedding_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """应用关闭期间重新向量化请求应返回 503 且不创建作业。"""
    embedding_client.app.state.application_shutdown_state = make_shutdown_state()

    user = seed_current_user(session)
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )
    chunk_models = _chunking_module()
    chunk_job = chunk_models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="succeeded",
        chunker_name="docling_hybrid",
        chunk_config_json={},
    )
    session.add(chunk_job)
    session.commit()
    session.refresh(chunk_job)

    emb_models = _embedding_module()
    try:
        response = embedding_client.post(
            f"/api/document-chunk-jobs/{chunk_job.id}/re-embed",
        )
    finally:
        delattr(embedding_client.app.state, "application_shutdown_state")

    assert response.status_code == 503
    assert "shutting down" in response.text.lower()
    # 确认未创建任何向量化作业
    jobs = session.exec(select(emb_models.DocumentEmbeddingJob)).all()
    assert jobs == []


# ═══════════════════════════════════════════════════════════════════════
# 8.8  run_reembed_job 后台执行器 — 成功执行和失败处理
# ═══════════════════════════════════════════════════════════════════════


def test_run_reembed_job_success(
    embedding_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """后台执行器应成功将 queued 作业执行完成。"""
    emb_models = _embedding_module()

    user = seed_current_user(session)
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )
    chunk_models = _chunking_module()
    chunk_job = chunk_models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="succeeded",
        chunker_name="docling_hybrid",
        chunk_config_json={},
    )
    session.add(chunk_job)
    session.commit()
    session.refresh(chunk_job)

    # 创建 chunks
    for i in range(2):
        session.add(
            chunk_models.DocumentChunk(
                chunk_job_id=chunk_job.id,
                parsed_document_id=parsed.id,
                owner_user_id=user.id,
                sequence_index=i,
                text=f"Test chunk {i}",
                chunk_type="text",
                source_segment_indices=[0],
            )
        )
    session.commit()

    # 创建 queued 向量化作业
    queued_job = emb_models.DocumentEmbeddingJob(
        chunk_job_id=chunk_job.id,
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="queued",
        embedder_name="openai_compatible",
        model="Qwen/Qwen3-Embedding-4B",
        dimensions=2560,
        config_json={"model": "Qwen/Qwen3-Embedding-4B", "dimensions": 2560},
    )
    session.add(queued_job)
    session.commit()
    session.refresh(queued_job)

    # 导入 run_reembed_job
    routes_mod = import_module("app.api.routes.document_embedding")
    adapter_mod = import_module("app.services.embedding_adapter")

    # 创建 fake adapter
    class FakeAdapter:
        def embed(self, texts):
            return [
                adapter_mod.EmbeddingResult(index=i, embedding=[0.1] * 2560)
                for i in range(len(texts))
            ]

    fake_adapter = FakeAdapter()

    def session_factory():
        from contextlib import contextmanager

        @contextmanager
        def _factory():
            yield session

        return _factory()

    routes_mod.run_reembed_job(
        queued_job.id,
        session_factory=_session_factory(session),
        embedding_adapter=fake_adapter,
        shutdown_state=None,
    )

    # 刷新作业状态
    session.refresh(queued_job)
    assert queued_job.status == "succeeded"
    assert queued_job.embedding_count == 2

    # 验证向量结果已持久化
    embeddings = session.exec(
        select(emb_models.DocumentEmbedding).where(
            emb_models.DocumentEmbedding.embedding_job_id == queued_job.id,
        )
    ).all()
    assert len(embeddings) == 2
    assert embeddings[0].dimensions == 2560


def test_run_reembed_job_failure_marks_job_failed(
    embedding_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """后台执行器遇到 API 错误时应将作业标记为 failed。"""
    emb_models = _embedding_module()

    user = seed_current_user(session)
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )
    chunk_models = _chunking_module()
    chunk_job = chunk_models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="succeeded",
        chunker_name="docling_hybrid",
        chunk_config_json={},
    )
    session.add(chunk_job)
    session.commit()
    session.refresh(chunk_job)

    session.add(
        chunk_models.DocumentChunk(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed.id,
            owner_user_id=user.id,
            sequence_index=0,
            text="Chunk for failure test",
            chunk_type="text",
            source_segment_indices=[0],
        )
    )
    session.commit()

    queued_job = emb_models.DocumentEmbeddingJob(
        chunk_job_id=chunk_job.id,
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="queued",
        embedder_name="openai_compatible",
        model="Qwen/Qwen3-Embedding-4B",
        dimensions=2560,
        config_json={},
    )
    session.add(queued_job)
    session.commit()
    session.refresh(queued_job)

    routes_mod = import_module("app.api.routes.document_embedding")
    adapter_mod = import_module("app.services.embedding_adapter")

    class FailingAdapter:
        def embed(self, texts):
            raise adapter_mod.EmbeddingAPIError("API failure", status_code=500)

    routes_mod.run_reembed_job(
        queued_job.id,
        session_factory=_session_factory(session),
        embedding_adapter=FailingAdapter(),
        shutdown_state=None,
    )

    session.refresh(queued_job)
    assert queued_job.status == "failed"
    assert queued_job.error_code is not None
    assert "API failure" in (queued_job.error_message or "")


# ═══════════════════════════════════════════════════════════════════════
# 8.9  run_reembed_job — shutdown 快速失败
# ═══════════════════════════════════════════════════════════════════════


def test_run_reembed_job_shutdown_fast_fail(
    embedding_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """shutdown 期间后台执行器应将作业标记为 process_shutdown 且不调用 API。"""
    emb_models = _embedding_module()

    user = seed_current_user(session)
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )
    chunk_models = _chunking_module()
    chunk_job = chunk_models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="succeeded",
        chunker_name="docling_hybrid",
        chunk_config_json={},
    )
    session.add(chunk_job)
    session.commit()
    session.refresh(chunk_job)

    session.add(
        chunk_models.DocumentChunk(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed.id,
            owner_user_id=user.id,
            sequence_index=0,
            text="Chunk",
            chunk_type="text",
            source_segment_indices=[0],
        )
    )
    session.commit()

    queued_job = emb_models.DocumentEmbeddingJob(
        chunk_job_id=chunk_job.id,
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="queued",
        embedder_name="openai_compatible",
        model="Qwen/Qwen3-Embedding-4B",
        dimensions=2560,
        config_json={},
    )
    session.add(queued_job)
    session.commit()
    session.refresh(queued_job)

    routes_mod = import_module("app.api.routes.document_embedding")

    call_count = [0]

    class RecordingAdapter:
        def embed(self, texts):
            call_count[0] += 1
            return []

    routes_mod.run_reembed_job(
        queued_job.id,
        session_factory=_session_factory(session),
        embedding_adapter=RecordingAdapter(),
        shutdown_state=make_shutdown_state(),
    )

    session.refresh(queued_job)
    assert queued_job.status == "failed"
    assert queued_job.error_code == "process_shutdown"
    # shutdown 期间不应调用 API
    assert call_count[0] == 0


# ═══════════════════════════════════════════════════════════════════════
# 8.10 run_reembed_job — 新结果成功后旧作业被标记为 superseded
# ═══════════════════════════════════════════════════════════════════════


def test_run_reembed_job_supersedes_old_jobs(
    embedding_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """新向量化作业成功后，旧 succeeded 作业应被标记为 superseded。"""
    emb_models = _embedding_module()

    user = seed_current_user(session)
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )
    chunk_models = _chunking_module()
    chunk_job = chunk_models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="succeeded",
        chunker_name="docling_hybrid",
        chunk_config_json={},
    )
    session.add(chunk_job)
    session.commit()
    session.refresh(chunk_job)

    for i in range(2):
        session.add(
            chunk_models.DocumentChunk(
                chunk_job_id=chunk_job.id,
                parsed_document_id=parsed.id,
                owner_user_id=user.id,
                sequence_index=i,
                text=f"Chunk {i}",
                chunk_type="text",
                source_segment_indices=[0],
            )
        )
    session.commit()

    # 创建旧的成功作业
    old_job = emb_models.DocumentEmbeddingJob(
        chunk_job_id=chunk_job.id,
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="succeeded",
        embedder_name="openai_compatible",
        model="old-model",
        dimensions=2560,
        embedding_count=2,
        config_json={"model": "old-model"},
    )
    session.add(old_job)
    session.commit()
    session.refresh(old_job)

    # 创建新的 queued 作业
    new_job = emb_models.DocumentEmbeddingJob(
        chunk_job_id=chunk_job.id,
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="queued",
        embedder_name="openai_compatible",
        model="new-model",
        dimensions=2560,
        config_json={"model": "new-model"},
    )
    session.add(new_job)
    session.commit()
    session.refresh(new_job)

    routes_mod = import_module("app.api.routes.document_embedding")
    adapter_mod = import_module("app.services.embedding_adapter")

    class FakeAdapter:
        def embed(self, texts):
            return [
                adapter_mod.EmbeddingResult(index=i, embedding=[0.2] * 2560)
                for i in range(len(texts))
            ]

    routes_mod.run_reembed_job(
        new_job.id,
        session_factory=_session_factory(session),
        embedding_adapter=FakeAdapter(),
        shutdown_state=None,
    )

    session.refresh(new_job)
    session.refresh(old_job)

    assert new_job.status == "succeeded"
    assert old_job.status == "superseded"


# ═══════════════════════════════════════════════════════════════════════
# 8.11 重新向量化不重新解析或分块
# ═══════════════════════════════════════════════════════════════════════


def test_run_reembed_job_does_not_call_parser_or_chunker(
    embedding_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """重新向量化应直接使用已有 chunks 文本，不调用解析或分块适配器。"""
    emb_models = _embedding_module()

    user = seed_current_user(session)
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )
    chunk_models = _chunking_module()
    chunk_job = chunk_models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="succeeded",
        chunker_name="docling_hybrid",
        chunk_config_json={},
    )
    session.add(chunk_job)
    session.commit()
    session.refresh(chunk_job)

    session.add(
        chunk_models.DocumentChunk(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed.id,
            owner_user_id=user.id,
            sequence_index=0,
            text="Pre-existing chunk text",
            chunk_type="text",
            source_segment_indices=[0],
        )
    )
    session.commit()

    queued_job = emb_models.DocumentEmbeddingJob(
        chunk_job_id=chunk_job.id,
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="queued",
        embedder_name="openai_compatible",
        model="Qwen/Qwen3-Embedding-4B",
        dimensions=2560,
        config_json={},
    )
    session.add(queued_job)
    session.commit()
    session.refresh(queued_job)

    routes_mod = import_module("app.api.routes.document_embedding")
    adapter_mod = import_module("app.services.embedding_adapter")

    received_texts = []

    class RecordingAdapter:
        def embed(self, texts):
            received_texts.extend(texts)
            return [
                adapter_mod.EmbeddingResult(index=i, embedding=[0.1] * 2560)
                for i in range(len(texts))
            ]

    routes_mod.run_reembed_job(
        queued_job.id,
        session_factory=_session_factory(session),
        embedding_adapter=RecordingAdapter(),
        shutdown_state=None,
    )

    # 应使用已有 chunk 的文本进行向量化
    assert received_texts == ["Pre-existing chunk text"]
    # 作业应成功完成
    session.refresh(queued_job)
    assert queued_job.status == "succeeded"


# ═══════════════════════════════════════════════════════════════════════
# Utility
# ═══════════════════════════════════════════════════════════════════════


def _session_factory(session: Session):
    """将静态 session 包装为 context manager，供 run_reembed_job 依赖注入使用。"""
    from contextlib import contextmanager

    @contextmanager
    def factory():
        yield session

    return factory
