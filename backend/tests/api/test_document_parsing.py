from collections.abc import Generator
from contextlib import suppress
from datetime import UTC, datetime
from importlib import import_module
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import get_settings
from app.db.session import get_session
from app.main import app
from app.models.user import User
from app.services.users import DEFAULT_USER_ID
from tests.document_parsing_helpers import make_uploaded_file, make_user

JOB_RESPONSE_FIELDS = {
    "id",
    "uploaded_file_id",
    "owner_user_id",
    "status",
    "parser_name",
    "parser_version",
    "attempt_count",
    "started_at",
    "finished_at",
    "error_code",
    "error_message",
    "created_at",
    "updated_at",
}


@pytest.fixture
def session() -> Generator[Session]:
    import_module("app.models.uploaded_file")
    with suppress(ModuleNotFoundError):
        import_module("app.models.document_parsing")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as test_session:
        yield test_session


@pytest.fixture
def parse_client(monkeypatch, session: Session, tmp_path) -> Generator[TestClient]:
    monkeypatch.setenv("UPLOAD_STORAGE_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("DOCUMENT_PARSE_ARTIFACT_DIR", str(tmp_path / "parsed"))
    monkeypatch.setenv("DOCUMENT_PARSE_ALLOWED_CONTENT_TYPES", "application/pdf,text/plain")
    monkeypatch.setenv("DOCUMENT_PARSE_ALLOWED_EXTENSIONS", ".pdf,.txt")
    get_settings.cache_clear()

    with suppress(ModuleNotFoundError):
        dispatcher = import_module("app.services.document_parse_dispatcher")
        monkeypatch.setattr(dispatcher, "run_parse_job", lambda job_id: None)

    def override_get_session() -> Generator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def seed_current_user(session: Session) -> User:
    created_at = datetime(2026, 6, 5, tzinfo=UTC)
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


def get_models_module():
    return import_module("app.models.document_parsing")


# 测试 POST /api/uploads/{upload_id}/parse 成功创建异步解析作业。
def test_post_upload_parse_returns_accepted_job(
    parse_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    user = seed_current_user(session)
    upload = make_uploaded_file(session, tmp_path / "uploads", user)

    response = parse_client.post(f"/api/uploads/{upload.id}/parse")

    assert response.status_code == 202
    payload = response.json()
    assert set(payload) == JOB_RESPONSE_FIELDS
    assert payload["uploaded_file_id"] == str(upload.id)
    assert payload["owner_user_id"] == str(user.id)
    assert payload["status"] in {"queued", "running"}
    assert payload["created_at"].endswith("Z")


# 测试当前用户不可用时拒绝创建无归属解析作业。
def test_post_upload_parse_rejects_when_current_user_unavailable(
    parse_client: TestClient,
) -> None:
    response = parse_client.post(f"/api/uploads/{uuid4()}/parse")

    assert response.status_code == 503
    assert response.json() == {"detail": "Current user is unavailable"}


# 测试非归属上传文件不能被当前用户解析。
def test_post_upload_parse_rejects_foreign_upload(
    parse_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    seed_current_user(session)
    other_user = make_user(session, display_name="Other User")
    upload = make_uploaded_file(session, tmp_path / "uploads", other_user)

    response = parse_client.post(f"/api/uploads/{upload.id}/parse")

    assert response.status_code == 404
    assert response.json() == {"detail": "Upload not found"}


# 测试已上传但不符合解析策略的文件返回 415。
def test_post_upload_parse_rejects_unsupported_type(
    parse_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    user = seed_current_user(session)
    upload = make_uploaded_file(
        session,
        tmp_path / "uploads",
        user,
        content=b"MZ executable",
        original_filename="malware.exe",
        content_type="application/x-msdownload",
    )

    response = parse_client.post(f"/api/uploads/{upload.id}/parse")

    assert response.status_code == 415
    assert "unsupported" in response.text.lower()


# 测试重复运行中解析固定返回 409，并携带已有作业和上传文档信息。
def test_post_upload_parse_returns_409_with_job_and_document_info_for_running_job(
    parse_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    models = get_models_module()
    user = seed_current_user(session)
    upload = make_uploaded_file(
        session,
        tmp_path / "uploads",
        user,
        original_filename="already-running.pdf",
    )
    existing = models.DocumentParseJob(
        uploaded_file_id=upload.id,
        owner_user_id=user.id,
        status="running",
        parser_name="docling",
    )
    session.add(existing)
    session.commit()
    session.refresh(existing)

    response = parse_client.post(f"/api/uploads/{upload.id}/parse")

    assert response.status_code == 409
    payload = response.json()
    assert set(payload) == {"detail", "job", "uploaded_file"}
    assert payload["job"]["id"] == str(existing.id)
    assert payload["job"]["status"] == "running"
    assert payload["uploaded_file"] == {
        "id": str(upload.id),
        "original_filename": "already-running.pdf",
        "content_type": "application/pdf",
        "byte_size": upload.byte_size,
        "status": "stored",
    }


# 测试当前用户可以查询自己的解析作业状态。
def test_get_document_parse_job_returns_owned_job(
    parse_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    models = get_models_module()
    user = seed_current_user(session)
    upload = make_uploaded_file(session, tmp_path / "uploads", user)
    job = models.DocumentParseJob(
        uploaded_file_id=upload.id,
        owner_user_id=user.id,
        status="failed",
        error_code="parse_failed",
        error_message="bad file",
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    response = parse_client.get(f"/api/document-parse-jobs/{job.id}")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == JOB_RESPONSE_FIELDS
    assert payload["id"] == str(job.id)
    assert payload["uploaded_file_id"] == str(upload.id)
    assert payload["status"] == "failed"
    assert payload["error_code"] == "parse_failed"
    assert payload["error_message"] == "bad file"


# 测试不能查询其他用户的解析作业。
def test_get_document_parse_job_rejects_foreign_job(
    parse_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    models = get_models_module()
    seed_current_user(session)
    other_user = make_user(session, display_name="Other User")
    upload = make_uploaded_file(session, tmp_path / "uploads", other_user)
    job = models.DocumentParseJob(uploaded_file_id=upload.id, owner_user_id=other_user.id)
    session.add(job)
    session.commit()

    response = parse_client.get(f"/api/document-parse-jobs/{job.id}")

    assert response.status_code == 404


# 测试读取上传文件最新成功解析结果时返回产物 key、元数据和片段数量。
def test_get_uploaded_file_parsed_document_returns_latest_successful_result(
    parse_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    models = get_models_module()
    user = seed_current_user(session)
    upload = make_uploaded_file(session, tmp_path / "uploads", user)
    job = models.DocumentParseJob(
        uploaded_file_id=upload.id,
        owner_user_id=user.id,
        status="succeeded",
    )
    session.add(job)
    session.commit()
    parsed = models.ParsedDocument(
        uploaded_file_id=upload.id,
        parse_job_id=job.id,
        owner_user_id=user.id,
        source_checksum_sha256=upload.checksum_sha256,
        markdown_storage_key="parsed/u/f/j/content.md",
        text_storage_key="parsed/u/f/j/content.txt",
        docling_json_storage_key="parsed/u/f/j/docling.json",
        title="Lecture",
        page_count=1,
        metadata_json={"parser": "docling"},
    )
    session.add(parsed)
    session.commit()
    session.refresh(parsed)
    session.add(
        models.DocumentSegment(
            parsed_document_id=parsed.id,
            owner_user_id=user.id,
            sequence_index=0,
            segment_type="paragraph",
            page_no=1,
            heading_path=["Lecture"],
            text="Body",
            metadata_json={"docling_ref": "#/texts/0"},
        )
    )
    session.commit()

    response = parse_client.get(f"/api/uploads/{upload.id}/parsed-document")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(parsed.id)
    assert payload["uploaded_file_id"] == str(upload.id)
    assert payload["markdown_storage_key"] == "parsed/u/f/j/content.md"
    assert payload["text_storage_key"] == "parsed/u/f/j/content.txt"
    assert payload["docling_json_storage_key"] == "parsed/u/f/j/docling.json"
    assert payload["metadata"] == {"parser": "docling"}
    assert payload["segment_count"] == 1


# 测试上传文件尚无成功解析结果时返回明确空状态。
def test_get_uploaded_file_parsed_document_returns_not_found_when_not_parsed(
    parse_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    user = seed_current_user(session)
    upload = make_uploaded_file(session, tmp_path / "uploads", user)

    response = parse_client.get(f"/api/uploads/{upload.id}/parsed-document")

    assert response.status_code == 404
    assert "not parsed" in response.text.lower()


# 测试结构片段分页按 sequence_index序列索引 返回。
def test_get_parsed_document_segments_returns_paginated_ordered_segments(
    parse_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    models = get_models_module()
    user = seed_current_user(session)
    upload = make_uploaded_file(session, tmp_path / "uploads", user)
    job = models.DocumentParseJob(
        uploaded_file_id=upload.id,
        owner_user_id=user.id,
        status="succeeded",
    )
    session.add(job)
    session.commit()
    parsed = models.ParsedDocument(
        uploaded_file_id=upload.id,
        parse_job_id=job.id,
        owner_user_id=user.id,
        source_checksum_sha256=upload.checksum_sha256,
        markdown_storage_key="parsed/u/f/j/content.md",
        text_storage_key="parsed/u/f/j/content.txt",
        docling_json_storage_key="parsed/u/f/j/docling.json",
    )
    session.add(parsed)
    session.commit()
    session.refresh(parsed)
    for index in [2, 0, 1]:
        session.add(
            models.DocumentSegment(
                parsed_document_id=parsed.id,
                owner_user_id=user.id,
                sequence_index=index,
                segment_type="paragraph",
                text=f"Segment {index}",
            )
        )
    session.commit()

    response = parse_client.get(f"/api/parsed-documents/{parsed.id}/segments?offset=1&limit=2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["offset"] == 1
    assert payload["limit"] == 2
    assert [item["sequence_index"] for item in payload["items"]] == [1, 2]
    assert [item["text"] for item in payload["items"]] == ["Segment 1", "Segment 2"]
