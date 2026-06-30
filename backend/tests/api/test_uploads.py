import logging
from collections.abc import Generator
from contextlib import suppress
from datetime import UTC, datetime
from hashlib import sha256
from importlib import import_module
from pathlib import PurePosixPath
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import get_settings
from app.db.session import get_session
from app.main import app
from app.models.user import User
from app.services.users import DEFAULT_USER_ID

RESPONSE_FIELDS = {
    "id",
    "owner_user_id",
    "original_filename",
    "content_type",
    "byte_size",
    "storage_key",
    "checksum_sha256",
    "status",
    "error_message",
    "deleted_at",
    "created_at",
    "updated_at",
}


@pytest.fixture
def session() -> Generator[Session]:
    with suppress(ModuleNotFoundError):
        import_module("app.models.uploaded_file")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as test_session:
        yield test_session


@pytest.fixture
def upload_storage_dir(tmp_path):
    return tmp_path / "uploads-root"


@pytest.fixture
def uploads_client(
    monkeypatch,
    session: Session,
    upload_storage_dir,
) -> Generator[TestClient]:
    monkeypatch.setenv("UPLOAD_STORAGE_DIR", str(upload_storage_dir))
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "8")
    monkeypatch.setenv("ALLOWED_UPLOAD_CONTENT_TYPES", "text/plain,application/pdf")
    get_settings.cache_clear()

    def override_get_session() -> Generator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def seed_current_user(session: Session) -> None:
    created_at = datetime(2026, 5, 25, tzinfo=UTC)
    session.add(
        User(
            id=DEFAULT_USER_ID,
            display_name="Default User",
            status="active",
            created_at=created_at,
            updated_at=created_at,
        )
    )
    session.commit()


def count_stored_uploads(session: Session) -> int:
    try:
        UploadedFile = import_module("app.models.uploaded_file").UploadedFile
    except ModuleNotFoundError:
        return 0

    return len(session.exec(select(UploadedFile).where(UploadedFile.status == "stored")).all())


# 测试 POST /api/uploads 会从 multipart 文件创建 stored 上传记录，
# 使用当前用户归属而不是表单归属字段，并返回约定响应结构。
def test_post_uploads_returns_created_record_and_stores_file(
    uploads_client: TestClient,
    session: Session,
    upload_storage_dir,
) -> None:
    seed_current_user(session)
    content = b"notes"

    response = uploads_client.post(
        "/api/uploads",
        data={"owner_user_id": str(uuid4())},
        files={"file": ("course-notes.txt", content, "text/plain")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert set(payload) == RESPONSE_FIELDS
    assert payload["owner_user_id"] == str(DEFAULT_USER_ID)
    assert payload["original_filename"] == "course-notes.txt"
    assert payload["content_type"] == "text/plain"
    assert payload["byte_size"] == len(content)
    assert payload["checksum_sha256"] == sha256(content).hexdigest()
    assert payload["status"] == "stored"
    assert payload["error_message"] is None
    assert payload["deleted_at"] is None
    assert payload["created_at"].endswith("Z")
    assert payload["updated_at"].endswith("Z")

    storage_key = PurePosixPath(payload["storage_key"])
    assert storage_key.name != "course-notes.txt"
    assert upload_storage_dir.joinpath(*storage_key.parts).read_bytes() == content


# 测试缺少 multipart 文件字段时会返回可诊断错误，
# 且不会创建 stored 上传记录。
def test_post_uploads_requires_file_field(
    uploads_client: TestClient,
    session: Session,
) -> None:
    seed_current_user(session)

    response = uploads_client.post("/api/uploads", data={})

    assert response.status_code == 422
    assert "file" in response.text.lower()
    assert count_stored_uploads(session) == 0


# 测试当前用户不可解析时拒绝上传，
# 避免创建无归属元数据或成功保存文件。
def test_post_uploads_rejects_when_current_user_is_unavailable(
    uploads_client: TestClient,
    session: Session,
) -> None:
    response = uploads_client.post(
        "/api/uploads",
        files={"file": ("course-notes.txt", b"notes", "text/plain")},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Current user is unavailable"}
    assert count_stored_uploads(session) == 0


# 测试空文件会被拒绝，并且不会被记录为 stored 上传。
def test_post_uploads_rejects_empty_file(
    uploads_client: TestClient,
    session: Session,
) -> None:
    seed_current_user(session)

    response = uploads_client.post(
        "/api/uploads",
        files={"file": ("empty.txt", b"", "text/plain")},
    )

    assert response.status_code == 400
    assert "empty" in response.text.lower()
    assert count_stored_uploads(session) == 0


# 测试 API 边界会执行 max_upload_bytes 配置限制，
# 超限上传会返回错误且不会创建成功元数据。
def test_post_uploads_rejects_file_over_configured_size_limit(
    uploads_client: TestClient,
    session: Session,
) -> None:
    seed_current_user(session)

    response = uploads_client.post(
        "/api/uploads",
        files={"file": ("large.txt", b"123456789", "text/plain")},
    )

    assert response.status_code == 413
    assert "size" in response.text.lower()
    assert count_stored_uploads(session) == 0


# =========================================================================
# 日志记录测试（spec: API 路由层日志记录 — uploads.py）
# RED 阶段：当前 routes/uploads.py 未接入日志，以下测试预期全部失败。
# =========================================================================


# 测试用户不可用时返回 503 前应输出 ERROR 级别日志。
def test_post_uploads_logs_error_when_user_unavailable(
    uploads_client: TestClient,
    session: Session,
    caplog,
) -> None:
    caplog.set_level(logging.DEBUG)

    uploads_client.post(
        "/api/uploads",
        files={"file": ("notes.txt", b"content", "text/plain")},
    )

    route_records = [r for r in caplog.records if r.name == "app.api.routes.uploads"]
    assert any(r.levelname == "ERROR" for r in route_records)


# 测试文件超限时返回 413 前应输出 WARNING 级别日志。
def test_post_uploads_logs_warning_on_oversize(
    uploads_client: TestClient,
    session: Session,
    caplog,
) -> None:
    caplog.set_level(logging.DEBUG)
    seed_current_user(session)

    uploads_client.post(
        "/api/uploads",
        files={"file": ("large.txt", b"123456789", "text/plain")},
    )

    route_records = [r for r in caplog.records if r.name == "app.api.routes.uploads"]
    assert any(r.levelname == "WARNING" for r in route_records)


# 测试空文件校验失败时返回 400 前应输出 WARNING 级别日志。
def test_post_uploads_logs_warning_on_empty_file(
    uploads_client: TestClient,
    session: Session,
    caplog,
) -> None:
    caplog.set_level(logging.DEBUG)
    seed_current_user(session)

    uploads_client.post(
        "/api/uploads",
        files={"file": ("empty.txt", b"", "text/plain")},
    )

    route_records = [r for r in caplog.records if r.name == "app.api.routes.uploads"]
    assert any(r.levelname == "WARNING" for r in route_records)
