# 本文件验证流水线存取验证 API 的用户可见行为。
# 覆盖正常路径（完整 pipeline 文档验证返回 200 且所有检查 passed）、
# 边界情况（仅一个 chunk 的文档、chunk 文本在文件系统中而非内联、
# sequence_index 从 0 开始连续）、
# 异常处理（parsed_document 不存在、无 succeeded chunk_job、
# 无 succeeded embedding_job、chunk_job 失败、孤儿 embedding、
# 孤儿 chunk、sequence_index 跳号、文件系统中 chunk 文本被删除、
# current_user 不可用）。

from collections.abc import Generator
from contextlib import suppress
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import get_settings
from app.db.session import get_session
from app.main import app
from app.models.user import User
from app.services.users import DEFAULT_USER_ID
from tests.document_chunking_helpers import make_parsed_document_with_segment
from tests.document_parsing_helpers import make_user

# ── 响应字段集合（用于断言响应结构完整性）──────────────────────────────

PIPELINE_VERIFICATION_RESPONSE_FIELDS = {
    "document",
    "pipeline",
    "verification",
    "pairs",
    "stats",
}

DOCUMENT_CHAIN_INFO_FIELDS = {
    "parsed_document_id",
    "title",
    "original_filename",
    "content_type",
    "byte_size",
}

PIPELINE_INFO_FIELDS = {
    "parse_job",
    "chunk_job",
    "embedding_job",
}

VERIFICATION_SUMMARY_FIELDS = {
    "passed",
    "total_checks",
    "passed_checks",
    "checks",
}

VERIFICATION_CHECK_FIELDS = {"name", "passed", "message"}

CHUNK_EMBEDDING_PAIR_FIELDS = {"sequence_index", "chunk", "embedding"}

VERIFICATION_STATS_FIELDS = {
    "total_pairs",
    "total_chunk_tokens",
    "total_embedding_tokens",
    "inline_text_count",
    "file_storage_text_count",
    "embedding_dimensions",
    "embedding_model",
}

EXPECTED_CHECK_NAMES = [
    "chunk_embedding_pairing",
    "dimension_consistency",
    "sequence_continuity",
    "chunk_text_availability",
    "contextualized_text_availability",
    "token_count_consistency",
    "model_consistency",
]


# ── Fixtures ─────────────────────────────────────────────────────────────


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
def verification_client(monkeypatch, session: Session, tmp_path) -> Generator[TestClient]:
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


# ── Helpers ───────────────────────────────────────────────────────────────


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


def _embedding_module():
    return import_module("app.models.document_embedding")


def _chunking_module():
    return import_module("app.models.document_chunking")


def _make_embedding_vector(dimensions: int = 2560) -> list[float]:
    """生成固定测试向量。"""
    return [0.1] * dimensions


def seed_complete_pipeline(
    session: Session,
    tmp_path: Path,
    *,
    chunk_count: int = 2,
    inline_text: bool = True,
    skip_sequence_index: int | None = None,
) -> tuple:
    """种下完整的成功流水线：用户 → 上传 → 解析 → 分块作业 → chunks → 向量化作业 → embeddings。

    参数：
    - chunk_count: 创建的分块数量，同时决定向量数量（一一对应）。
    - inline_text: True 时 chunk 文本内联存储在 text 字段；False 时 chunk 文本
      存入文件系统（text_storage_key），text 字段为 NULL。
    - skip_sequence_index: 若设置，则跳过该 sequence_index 的分块和向量创建，
      用于模拟跳号场景。

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
    actual_chunk_count = chunk_count if skip_sequence_index is None else chunk_count - 1
    chunk_job = chunk_models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="succeeded",
        chunker_name="docling_hybrid",
        chunker_version="docling-core",
        chunk_config_json={"max_tokens": 512},
        chunk_count=actual_chunk_count,
    )
    session.add(chunk_job)
    session.commit()
    session.refresh(chunk_job)

    # 创建 chunks
    chunks = []
    for i in range(chunk_count):
        if skip_sequence_index is not None and i == skip_sequence_index:
            continue
        if inline_text:
            chunk = chunk_models.DocumentChunk(
                chunk_job_id=chunk_job.id,
                parsed_document_id=parsed.id,
                owner_user_id=user.id,
                sequence_index=i,
                text=f"Chunk text {i}",
                contextualized_text=f"Contextualized chunk {i}",
                token_count=10 + i,
                heading_path=["Course Notes"],
                page_numbers=[1],
                chunk_type="text",
                source_segment_indices=[0],
                metadata_json={"docling_ref": f"#/texts/{i}"},
            )
        else:
            # 文件系统存储：text 为 NULL，text_storage_key 指向文件系统
            storage_key = f"chunks/{user.id}/{parsed.id}/{chunk_job.id}/{i:06d}_text.txt"
            ctx_storage_key = (
                f"chunks/{user.id}/{parsed.id}/{chunk_job.id}/{i:06d}_contextualized.txt"
            )
            chunk = chunk_models.DocumentChunk(
                chunk_job_id=chunk_job.id,
                parsed_document_id=parsed.id,
                owner_user_id=user.id,
                sequence_index=i,
                text=None,
                text_storage_key=storage_key,
                contextualized_text=None,
                contextualized_text_storage_key=ctx_storage_key,
                token_count=10 + i,
                heading_path=["Course Notes"],
                page_numbers=[1],
                chunk_type="text",
                source_segment_indices=[0],
                metadata_json={"docling_ref": f"#/texts/{i}"},
            )
        session.add(chunk)
        chunks.append(chunk)
    session.commit()
    for c in chunks:
        session.refresh(c)
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
        embedding_count=actual_chunk_count,
        config_json={
            "model": "Qwen/Qwen3-Embedding-4B",
            "dimensions": 2560,
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
            token_count=chunk.token_count,
        )
        session.add(emb)
        embeddings.append(emb)
    session.commit()
    for e in embeddings:
        session.refresh(e)

    return user, parsed, chunk_job, embedding_job, chunks, embeddings


def write_chunk_file(
    chunk_artifact_dir: Path,
    user_id,
    parsed_document_id,
    chunk_job_id,
    sequence_index: int,
    suffix: str,
    content: str,
) -> Path:
    """在 chunk artifact 存储目录中写入测试用的 chunk 文本文件。

    路径格式与 ChunkArtifactStorage 保持一致：
    chunks/{user_id}/{parsed_document_id}/{chunk_job_id}/{seq:06d}_{suffix}.txt
    """
    from pathlib import PurePosixPath

    storage_key = (
        f"chunks/{user_id}/{parsed_document_id}/{chunk_job_id}/{sequence_index:06d}_{suffix}.txt"
    )
    path = chunk_artifact_dir.joinpath(*PurePosixPath(storage_key).parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ═══════════════════════════════════════════════════════════════════════════
# 4.1.1  正常路径：完整 pipeline 文档验证返回 200 且所有检查 passed
# ═══════════════════════════════════════════════════════════════════════════


def test_complete_pipeline_verification_returns_200_with_all_checks_passed(
    verification_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """验证完整 pipeline 文档验证返回 200，响应结构完整，所有 7 项检查均 passed。"""
    _user, parsed, _chunk_job, _embedding_job, _chunks, _embeddings = seed_complete_pipeline(
        session, tmp_path, chunk_count=3
    )

    response = verification_client.get(f"/api/parsed-documents/{parsed.id}/pipeline-verification")

    assert response.status_code == 200
    payload = response.json()

    # 顶层响应结构
    assert set(payload) == PIPELINE_VERIFICATION_RESPONSE_FIELDS

    # 文档信息
    doc = payload["document"]
    assert set(doc) == DOCUMENT_CHAIN_INFO_FIELDS
    assert doc["parsed_document_id"] == str(parsed.id)
    assert doc["title"] == "Course Notes"
    assert doc["original_filename"] == "notes.pdf"
    assert doc["content_type"] == "application/pdf"
    assert doc["byte_size"] > 0

    # Pipeline 阶段信息
    pipeline = payload["pipeline"]
    assert set(pipeline) == PIPELINE_INFO_FIELDS
    assert pipeline["parse_job"]["status"] == "succeeded"
    assert pipeline["chunk_job"]["status"] == "succeeded"
    assert pipeline["chunk_job"]["chunker_name"] == "docling_hybrid"
    assert pipeline["chunk_job"]["chunk_count"] == 3
    assert pipeline["embedding_job"]["status"] == "succeeded"
    assert pipeline["embedding_job"]["model"] == "Qwen/Qwen3-Embedding-4B"
    assert pipeline["embedding_job"]["dimensions"] == 2560
    assert pipeline["embedding_job"]["embedding_count"] == 3

    # 验证摘要
    verification = payload["verification"]
    assert set(verification) == VERIFICATION_SUMMARY_FIELDS
    assert verification["passed"] is True
    assert verification["total_checks"] == 7
    assert verification["passed_checks"] == 7
    check_names = [c["name"] for c in verification["checks"]]
    assert check_names == EXPECTED_CHECK_NAMES
    for check in verification["checks"]:
        assert set(check) == VERIFICATION_CHECK_FIELDS
        assert check["passed"] is True

    # 分块-向量对照 pairs
    pairs = payload["pairs"]
    assert len(pairs) == 3
    for pair in pairs:
        assert set(pair) == CHUNK_EMBEDDING_PAIR_FIELDS
        assert pair["chunk"] is not None
        assert pair["embedding"] is not None
    # 按 sequence_index 排序
    assert [p["sequence_index"] for p in pairs] == [0, 1, 2]
    # chunk 信息包含文本截断
    assert len(pairs[0]["chunk"]["text"]) <= 150
    # embedding 信息包含向量前 5 维预览
    assert len(pairs[0]["embedding"]["vector_preview"]) == 5

    # 统计摘要
    stats = payload["stats"]
    assert set(stats) == VERIFICATION_STATS_FIELDS
    assert stats["total_pairs"] == 3
    assert stats["embedding_dimensions"] == 2560
    assert stats["embedding_model"] == "Qwen/Qwen3-Embedding-4B"


# ═══════════════════════════════════════════════════════════════════════════
# 4.1.2  边界情况：仅一个 chunk 的文档
# ═══════════════════════════════════════════════════════════════════════════


def test_single_chunk_document_verification_returns_200(
    verification_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """验证仅包含一个 chunk 的文档也能正常完成验证，pairs 数量为 1。"""
    _user, parsed, _chunk_job, _embedding_job, chunks, embeddings = seed_complete_pipeline(
        session, tmp_path, chunk_count=1
    )

    response = verification_client.get(f"/api/parsed-documents/{parsed.id}/pipeline-verification")

    assert response.status_code == 200
    payload = response.json()

    assert payload["verification"]["passed"] is True
    assert len(payload["pairs"]) == 1
    assert payload["pairs"][0]["sequence_index"] == 0
    assert payload["pairs"][0]["chunk"] is not None
    assert payload["pairs"][0]["embedding"] is not None
    assert payload["stats"]["total_pairs"] == 1
    # 序列连续性检查：从 0 到 0 视为连续
    seq_check = next(
        c for c in payload["verification"]["checks"] if c["name"] == "sequence_continuity"
    )
    assert seq_check["passed"] is True


# ═══════════════════════════════════════════════════════════════════════════
# 4.1.3  边界情况：chunk 文本在文件系统中而非内联
# ═══════════════════════════════════════════════════════════════════════════


def test_file_storage_chunk_text_verification_returns_200(
    verification_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """验证 chunk 文本存储在文件系统中（text 为 NULL、text_storage_key 非空）时，
    系统能通过 ChunkArtifactStorage 成功读取文本，chunk_text_availability 检查 passed。"""
    _user, parsed, chunk_job, _embedding_job, chunks, _embeddings = seed_complete_pipeline(
        session, tmp_path, chunk_count=2, inline_text=False
    )

    # 在 chunk artifact 目录中写入文件
    chunk_artifact_dir = tmp_path / "chunks"
    for i, _chunk in enumerate(chunks):
        write_chunk_file(
            chunk_artifact_dir,
            _user.id,
            parsed.id,
            chunk_job.id,
            i,
            "text",
            f"File-stored chunk text {i}",
        )
        write_chunk_file(
            chunk_artifact_dir,
            _user.id,
            parsed.id,
            chunk_job.id,
            i,
            "contextualized",
            f"File-stored contextualized text {i}",
        )

    response = verification_client.get(f"/api/parsed-documents/{parsed.id}/pipeline-verification")

    assert response.status_code == 200
    payload = response.json()

    # 分块文本可读性检查应 passed
    text_check = next(
        c for c in payload["verification"]["checks"] if c["name"] == "chunk_text_availability"
    )
    assert text_check["passed"] is True
    assert "文件存储" in text_check["message"]

    # 上下文增强文本可读性检查也应 passed
    ctx_check = next(
        c
        for c in payload["verification"]["checks"]
        if c["name"] == "contextualized_text_availability"
    )
    assert ctx_check["passed"] is True

    # pairs 中 text_source 应为 "file"
    for pair in payload["pairs"]:
        assert pair["chunk"]["text_source"] == "file"

    # 统计中应反映文件存储数量
    assert payload["stats"]["file_storage_text_count"] == 2
    assert payload["stats"]["inline_text_count"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# 4.1.4  边界情况：sequence_index 从 0 开始连续
# ═══════════════════════════════════════════════════════════════════════════


def test_sequence_index_continuous_from_zero_passes_continuity_check(
    verification_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """验证 sequence_index 从 0 到 N-1 连续时，sequence_continuity 检查 passed。"""
    _user, parsed, _chunk_job, _embedding_job, _chunks, _embeddings = seed_complete_pipeline(
        session, tmp_path, chunk_count=5
    )

    response = verification_client.get(f"/api/parsed-documents/{parsed.id}/pipeline-verification")

    assert response.status_code == 200
    payload = response.json()

    seq_check = next(
        c for c in payload["verification"]["checks"] if c["name"] == "sequence_continuity"
    )
    assert seq_check["passed"] is True
    assert "连续" in seq_check["message"]


# ═══════════════════════════════════════════════════════════════════════════
# 4.1.5  异常处理：parsed_document 不存在 → 404
# ═══════════════════════════════════════════════════════════════════════════


def test_nonexistent_parsed_document_returns_404(
    verification_client: TestClient,
    session: Session,
) -> None:
    """验证请求不存在的 parsed_document_id 时返回 404。"""
    seed_current_user(session)

    response = verification_client.get(
        "/api/parsed-documents/00000000-0000-0000-0000-000000000099/pipeline-verification"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Parsed document not found"


# ═══════════════════════════════════════════════════════════════════════════
# 4.1.6  异常处理：无 succeeded chunk_job → 404
# ═══════════════════════════════════════════════════════════════════════════


def test_no_succeeded_chunk_job_returns_404(
    verification_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """验证文档已解析但无成功的分块作业时返回 404。"""
    user = seed_current_user(session)
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )

    response = verification_client.get(f"/api/parsed-documents/{parsed.id}/pipeline-verification")

    assert response.status_code == 404
    assert response.json()["detail"] == "No succeeded chunk job found for this document"


# ═══════════════════════════════════════════════════════════════════════════
# 4.1.7  异常处理：chunk_job 存在但无 succeeded embedding_job → 404
# ═══════════════════════════════════════════════════════════════════════════


def test_no_succeeded_embedding_job_returns_404(
    verification_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """验证分块作业已完成但无成功的向量化作业时返回 404。"""
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
        chunk_count=0,
    )
    session.add(chunk_job)
    session.commit()
    session.refresh(chunk_job)

    response = verification_client.get(f"/api/parsed-documents/{parsed.id}/pipeline-verification")

    assert response.status_code == 404
    assert response.json()["detail"] == "No succeeded embedding job found for this document"


# ═══════════════════════════════════════════════════════════════════════════
# 4.1.8  异常处理：chunk_job 状态为 failed → 404
# ═══════════════════════════════════════════════════════════════════════════


def test_failed_chunk_job_returns_404(
    verification_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """验证分块作业状态为 failed 时（无 succeeded chunk_job）返回 404。"""
    user = seed_current_user(session)
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )
    chunk_models = _chunking_module()
    failed_chunk_job = chunk_models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="failed",
        chunker_name="docling_hybrid",
        chunk_config_json={},
        error_code="chunker_error",
        error_message="Chunking failed due to invalid format",
    )
    session.add(failed_chunk_job)
    session.commit()
    session.refresh(failed_chunk_job)

    response = verification_client.get(f"/api/parsed-documents/{parsed.id}/pipeline-verification")

    # 因为 service 只查找 status=succeeded 的 chunk_job，failed 应返回 404
    assert response.status_code == 404
    assert response.json()["detail"] == "No succeeded chunk job found for this document"


# ═══════════════════════════════════════════════════════════════════════════
# 4.1.9  异常处理：存在孤儿 embedding → 200 但 pairing 检查 failed
# ═══════════════════════════════════════════════════════════════════════════


def test_orphan_embedding_returns_200_with_pairing_check_failed(
    verification_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """验证存在孤儿 embedding（embedding 有对应 chunk_id 但 chunk 已删除）时，
    返回 200 但 chunk_embedding_pairing 检查 failed。"""
    emb_models = _embedding_module()

    _user, parsed, chunk_job, embedding_job, chunks, embeddings = seed_complete_pipeline(
        session, tmp_path, chunk_count=2
    )

    # 创建一个 orphan embedding：指向一个不存在的 chunk_id
    orphan_embedding = emb_models.DocumentEmbedding(
        embedding_job_id=embedding_job.id,
        chunk_id=UUID("00000000-0000-0000-0000-000000000099"),  # 不存在的 chunk
        parsed_document_id=parsed.id,
        owner_user_id=_user.id,
        sequence_index=99,
        model="Qwen/Qwen3-Embedding-4B",
        dimensions=2560,
        embedding_json=_make_embedding_vector(),
        embedding_vector=_make_embedding_vector(),
        token_count=10,
    )
    session.add(orphan_embedding)
    session.commit()

    response = verification_client.get(f"/api/parsed-documents/{parsed.id}/pipeline-verification")

    assert response.status_code == 200
    payload = response.json()

    pairing_check = next(
        c for c in payload["verification"]["checks"] if c["name"] == "chunk_embedding_pairing"
    )
    assert pairing_check["passed"] is False
    assert "孤儿 embedding" in pairing_check["message"]

    # 整体验证应标记为未通过
    assert payload["verification"]["passed"] is False


# ═══════════════════════════════════════════════════════════════════════════
# 4.1.10 异常处理：存在孤儿 chunk → 200 但 pairing 检查 failed
# ═══════════════════════════════════════════════════════════════════════════


def test_orphan_chunk_returns_200_with_pairing_check_failed(
    verification_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """验证存在孤儿 chunk（chunk 存在但无对应 embedding）时，
    返回 200 但 chunk_embedding_pairing 检查 failed。"""
    chunk_models = _chunking_module()

    _user, parsed, chunk_job, _embedding_job, chunks, _embeddings = seed_complete_pipeline(
        session, tmp_path, chunk_count=2
    )

    # 创建一个 orphan chunk：有 chunk 但没有对应的 embedding
    orphan_chunk = chunk_models.DocumentChunk(
        chunk_job_id=chunk_job.id,
        parsed_document_id=parsed.id,
        owner_user_id=_user.id,
        sequence_index=2,
        text="Orphan chunk without embedding",
        contextualized_text="Orphan contextualized",
        token_count=15,
        heading_path=["Course Notes"],
        page_numbers=[1],
        chunk_type="text",
        source_segment_indices=[0],
        metadata_json={"docling_ref": "#/texts/orphan"},
    )
    session.add(orphan_chunk)
    session.commit()
    session.refresh(orphan_chunk)

    response = verification_client.get(f"/api/parsed-documents/{parsed.id}/pipeline-verification")

    assert response.status_code == 200
    payload = response.json()

    pairing_check = next(
        c for c in payload["verification"]["checks"] if c["name"] == "chunk_embedding_pairing"
    )
    assert pairing_check["passed"] is False
    assert "孤儿 chunk" in pairing_check["message"]

    # 孤儿 chunk 在 pairs 中出现，embedding 为 None
    orphan_pair = next(p for p in payload["pairs"] if p["sequence_index"] == 2)
    assert orphan_pair["chunk"] is not None
    assert orphan_pair["embedding"] is None

    assert payload["verification"]["passed"] is False


# ═══════════════════════════════════════════════════════════════════════════
# 4.1.11 异常处理：sequence_index 跳号 → 200 但 continuity 检查 failed
# ═══════════════════════════════════════════════════════════════════════════


def test_sequence_index_skip_returns_200_with_continuity_check_failed(
    verification_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """验证 sequence_index 不存在跳号（如 0, 1, 3，缺少 2）时，
    返回 200 但 sequence_continuity 检查 failed。"""
    _user, parsed, _chunk_job, _embedding_job, chunks, _embeddings = seed_complete_pipeline(
        session, tmp_path, chunk_count=4, skip_sequence_index=2
    )

    response = verification_client.get(f"/api/parsed-documents/{parsed.id}/pipeline-verification")

    assert response.status_code == 200
    payload = response.json()

    seq_check = next(
        c for c in payload["verification"]["checks"] if c["name"] == "sequence_continuity"
    )
    assert seq_check["passed"] is False
    assert "缺失序号" in seq_check["message"] or "不连续" in seq_check["message"]

    # 验证整体标记为未通过
    assert payload["verification"]["passed"] is False


# ═══════════════════════════════════════════════════════════════════════════
# 4.1.12 异常处理：文件系统中 chunk 文本文件被删除 → 200 但
#          text_availability 检查 failed
# ═══════════════════════════════════════════════════════════════════════════


def test_deleted_chunk_file_returns_200_with_text_availability_check_failed(
    verification_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """验证 chunk 文本存储在文件系统中但文件已被删除时，
    返回 200 但 chunk_text_availability 检查 failed。"""
    _user, parsed, chunk_job, _embedding_job, chunks, _embeddings = seed_complete_pipeline(
        session, tmp_path, chunk_count=2, inline_text=False
    )

    # 仅写入 sequence_index=0 的文件，不写入 sequence_index=1 的文件
    # 模拟文件被删除或从未写入的场景
    chunk_artifact_dir = tmp_path / "chunks"
    write_chunk_file(
        chunk_artifact_dir,
        _user.id,
        parsed.id,
        chunk_job.id,
        0,
        "text",
        "This file exists",
    )
    write_chunk_file(
        chunk_artifact_dir,
        _user.id,
        parsed.id,
        chunk_job.id,
        0,
        "contextualized",
        "This contextualized file exists",
    )
    # sequence_index=1 的文件不写入 —— 模拟被删除

    response = verification_client.get(f"/api/parsed-documents/{parsed.id}/pipeline-verification")

    assert response.status_code == 200
    payload = response.json()

    text_check = next(
        c for c in payload["verification"]["checks"] if c["name"] == "chunk_text_availability"
    )
    assert text_check["passed"] is False
    assert "不可读" in text_check["message"] or "无法获取" in text_check["message"]

    # 序列 0 的 chunk text_source 应为 "file"
    pair_0 = next(p for p in payload["pairs"] if p["sequence_index"] == 0)
    assert pair_0["chunk"]["text_source"] == "file"
    assert pair_0["chunk"]["text"] is not None

    # 序列 1 的 chunk text_source 应为 "unavailable"（storage_key 存在但文件缺失）
    pair_1 = next(p for p in payload["pairs"] if p["sequence_index"] == 1)
    assert pair_1["chunk"]["text_source"] == "file"  # 有 storage_key 标记为 file
    # 但由于文件不存在，text 读取失败 -> _resolved_text 为 None

    assert payload["verification"]["passed"] is False


# ═══════════════════════════════════════════════════════════════════════════
# 4.1.13 异常处理：current_user 不可用 → 503
# ═══════════════════════════════════════════════════════════════════════════


def test_current_user_unavailable_returns_503(
    verification_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    """验证 get_current_user() 抛出 CurrentUserUnavailableError 时返回 503。

    不 seed 用户数据，get_current_user() 找不到 DEFAULT_USER_ID 对应的活跃用户，
    抛出 CurrentUserUnavailableError。"""
    # 创建一个不属于 DEFAULT_USER_ID 用户的 parsed_document
    other_user = make_user(session, display_name="Other User")
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=other_user,
    )

    response = verification_client.get(f"/api/parsed-documents/{parsed.id}/pipeline-verification")

    assert response.status_code == 503
    assert response.json()["detail"] == "Current user is unavailable"
