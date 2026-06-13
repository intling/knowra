# 本文件验证文档分块 HTTP API 的用户可见行为。
# 覆盖作业详情、chunk 列表与详情、重分块创建/冲突、空状态，以及跨用户隔离。

from collections.abc import Generator
from contextlib import suppress
from datetime import UTC, datetime
from importlib import import_module

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

JOB_RESPONSE_FIELDS = {
    "id",
    "parsed_document_id",
    "owner_user_id",
    "status",
    "chunker_name",
    "chunker_version",
    "chunk_config_json",
    "chunk_count",
    "attempt_count",
    "started_at",
    "finished_at",
    "error_code",
    "error_message",
    "created_at",
    "updated_at",
}

CHUNK_RESPONSE_FIELDS = {
    "id",
    "chunk_job_id",
    "parsed_document_id",
    "owner_user_id",
    "sequence_index",
    "text",
    "contextualized_text",
    "token_count",
    "heading_path",
    "page_numbers",
    "chunk_type",
    "source_segment_indices",
    "metadata",
    "created_at",
}


@pytest.fixture
# 提供 API 测试专用内存数据库，并注册上传、解析和分块模型。
# 这些测试验证路由行为，不依赖真实数据库。
def session() -> Generator[Session]:
    import_module("app.models.uploaded_file")
    import_module("app.models.document_parsing")
    with suppress(ModuleNotFoundError):
        import_module("app.models.document_chunking")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as test_session:
        yield test_session


@pytest.fixture
# 将 FastAPI 依赖替换为测试 session，并把上传/分块产物写入 tmp_path。
# 用于验证 API 响应，同时隔离本地存储副作用。
def chunking_client(monkeypatch, session: Session, tmp_path) -> Generator[TestClient]:
    monkeypatch.setenv("UPLOAD_STORAGE_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("DOCUMENT_CHUNK_ARTIFACT_STORAGE_DIR", str(tmp_path / "chunks"))
    get_settings.cache_clear()

    # 让被测路由始终使用当前测试 session，保证 seed 数据能被 API 读取。
    def override_get_session() -> Generator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    get_settings.cache_clear()


# 种下 API 认证层默认会解析到的当前用户。
# 权限相关测试以它作为被允许访问分块资源的主体。
def seed_current_user(session: Session) -> User:
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


# 种下当前用户的一次成功分块结果，并故意乱序插入两个 chunk。
# 列表 API 测试用它验证只读取成功作业，并按 sequence_index 排序返回。
def seed_successful_chunk_job(session: Session, tmp_path):
    models = import_module("app.models.document_chunking")
    user = seed_current_user(session)
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )
    job = models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="succeeded",
        chunker_name="docling_hybrid",
        chunker_version="docling-core",
        chunk_config_json={"max_tokens": 512},
        chunk_count=2,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    for index in [1, 0]:
        session.add(
            models.DocumentChunk(
                chunk_job_id=job.id,
                parsed_document_id=parsed.id,
                owner_user_id=user.id,
                sequence_index=index,
                text=f"Chunk {index}",
                contextualized_text=f"Course Notes\nChunk {index}",
                token_count=10 + index,
                heading_path=["Course Notes"],
                page_numbers=[1],
                chunk_type="text",
                source_segment_indices=[0],
                metadata_json={"docling_ref": f"#/texts/{index}"},
            )
        )
    session.commit()
    return user, parsed, job


# 作业详情接口应允许当前用户读取自己的分块作业。
# 响应需要包含前端展示所需的完整作业字段和配置快照。
def test_get_document_chunk_job_returns_owned_job(
    chunking_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    _user, _parsed, job = seed_successful_chunk_job(session, tmp_path)

    response = chunking_client.get(f"/api/document-chunk-jobs/{job.id}")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == JOB_RESPONSE_FIELDS
    assert payload["id"] == str(job.id)
    assert payload["status"] == "succeeded"
    assert payload["chunk_config_json"] == {"max_tokens": 512}


# 作业详情接口应把其他用户的作业伪装成不存在。
# 测试确保不会泄露私有失败原因，也不会暴露该 job 是否存在。
def test_get_document_chunk_job_rejects_foreign_job(
    chunking_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    models = import_module("app.models.document_chunking")
    seed_current_user(session)
    other_user = make_user(session, display_name="Other User")
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=other_user,
    )
    job = models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=other_user.id,
        status="failed",
        chunker_name="docling_hybrid",
        chunk_config_json={},
        error_message="private failure details",
    )
    session.add(job)
    session.commit()

    response = chunking_client.get(f"/api/document-chunk-jobs/{job.id}")

    assert response.status_code == 404
    assert "private failure details" not in response.text


# parsed document 最新分块作业接口应返回当前用户可见的最新作业。
# 前端用它在解析成功后区分“分块中/分块失败/分块完成”。
def test_get_latest_parsed_document_chunk_job_returns_newest_owned_job(
    chunking_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    models = import_module("app.models.document_chunking")
    user = seed_current_user(session)
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )
    older_job = models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="succeeded",
        chunker_name="docling_hybrid",
        chunk_config_json={},
        created_at=datetime(2026, 6, 12, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 6, 12, 0, 0, tzinfo=UTC),
    )
    latest_job = models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="running",
        chunker_name="docling_hybrid",
        chunk_config_json={},
        created_at=datetime(2026, 6, 12, 0, 1, tzinfo=UTC),
        updated_at=datetime(2026, 6, 12, 0, 1, tzinfo=UTC),
    )
    session.add(older_job)
    session.add(latest_job)
    session.commit()
    session.refresh(latest_job)

    response = chunking_client.get(f"/api/parsed-documents/{parsed.id}/chunk-job")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == JOB_RESPONSE_FIELDS
    assert payload["id"] == str(latest_job.id)
    assert payload["status"] == "running"


# 没有分块作业时按 parsed document 查询最新作业应返回 404。
# 前端据此展示稳定空状态，而不是误用 parsed_document_id 当作 job_id。
def test_get_latest_parsed_document_chunk_job_returns_404_when_missing(
    chunking_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    user = seed_current_user(session)
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )

    response = chunking_client.get(f"/api/parsed-documents/{parsed.id}/chunk-job")

    assert response.status_code == 404
    assert response.json() == {"detail": "Chunk job not found"}


# chunk 列表接口应选择解析结果的成功分块作业，并按 sequence_index 返回分页数据。
# 测试还确认列表项携带前端展示所需字段。
def test_get_parsed_document_chunks_returns_latest_active_successful_job_in_order(
    chunking_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    _user, parsed, _job = seed_successful_chunk_job(session, tmp_path)

    response = chunking_client.get(f"/api/parsed-documents/{parsed.id}/chunks?offset=0&limit=10")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["offset"] == 0
    assert payload["limit"] == 10
    assert [item["sequence_index"] for item in payload["items"]] == [0, 1]
    assert set(payload["items"][0]) == CHUNK_RESPONSE_FIELDS


# 当解析结果尚无成功分块作业时，chunk 列表接口应返回空分页而不是 404。
# 这样前端可以稳定展示“暂无分块”的空状态。
def test_get_parsed_document_chunks_returns_empty_state_when_no_successful_job(
    chunking_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    user = seed_current_user(session)
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )

    response = chunking_client.get(f"/api/parsed-documents/{parsed.id}/chunks")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "offset": 0, "limit": 50}


# chunk 详情接口应返回当前用户 chunk 的正文、上下文化文本和来源元数据。
# 这些字段用于问答引用展示或分块调试查看。
def test_get_document_chunk_returns_detail(
    chunking_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    models = import_module("app.models.document_chunking")
    _user, _parsed, _job = seed_successful_chunk_job(session, tmp_path)
    chunk = session.exec(
        select(models.DocumentChunk).where(models.DocumentChunk.sequence_index == 0)
    ).one()

    response = chunking_client.get(f"/api/document-chunks/{chunk.id}")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == CHUNK_RESPONSE_FIELDS
    assert payload["text"] == "Chunk 0"
    assert payload["contextualized_text"] == "Course Notes\nChunk 0"
    assert payload["metadata"] == {"docling_ref": "#/texts/0"}


# 重分块接口遇到同一解析结果已有 running 作业时应返回 409。
# 响应需要带回已有作业，避免前端重复排队或误判状态。
def test_post_rechunk_returns_409_when_job_is_already_running(
    chunking_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    models = import_module("app.models.document_chunking")
    user = seed_current_user(session)
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )
    running_job = models.DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="running",
        chunker_name="docling_hybrid",
        chunk_config_json={},
    )
    session.add(running_job)
    session.commit()
    session.refresh(running_job)

    response = chunking_client.post(f"/api/parsed-documents/{parsed.id}/rechunk")

    assert response.status_code == 409
    assert response.json()["job"]["id"] == str(running_job.id)


# 原始上传文件可读且参数合法时，重分块接口应创建新作业并返回 202。
# 响应字段需要与作业详情接口保持一致。
def test_post_rechunk_returns_202_and_created_job(
    chunking_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    user = seed_current_user(session)
    _owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )

    response = chunking_client.post(
        f"/api/parsed-documents/{parsed.id}/rechunk",
        json={"max_tokens": 256, "merge_peers": False},
    )

    assert response.status_code == 202
    payload = response.json()
    assert set(payload) == JOB_RESPONSE_FIELDS
    assert payload["parsed_document_id"] == str(parsed.id)
    assert payload["status"] in {"queued", "running", "succeeded"}


# 原始上传记录缺失时，重分块接口应返回明确错误。
# 测试同时确认接口不会回退读取旧 docling.json，确保重分块基于原始文件。
def test_post_rechunk_rejects_missing_original_upload_file(
    chunking_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    user = seed_current_user(session)
    _owner, upload, _parse_job, parsed = make_parsed_document_with_segment(
        session,
        tmp_path / "uploads",
        user=user,
    )
    session.delete(upload)
    session.commit()

    response = chunking_client.post(f"/api/parsed-documents/{parsed.id}/rechunk")

    assert response.status_code == 404
    assert response.json() == {"detail": "Original uploaded file is unavailable"}
    assert "docling.json" not in response.text.lower()
