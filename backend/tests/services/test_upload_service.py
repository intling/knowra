import logging
from collections.abc import Generator
from datetime import UTC, datetime
from hashlib import sha256
from importlib import import_module
from io import BytesIO
from pathlib import PurePosixPath

import pytest
from fastapi import UploadFile
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from starlette.datastructures import Headers

from app.models.user import User


def get_uploaded_file_model():
    return import_module("app.models.uploaded_file").UploadedFile


def get_uploads_module():
    return import_module("app.services.uploads")


@pytest.fixture
def session() -> Generator[Session]:
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
def user(session: Session) -> User:
    created_at = datetime(2026, 5, 25, tzinfo=UTC)
    user = User(
        display_name="Upload Owner",
        status="active",
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def make_upload_file(
    content: bytes,
    *,
    filename: str = "course-notes.pdf",
    content_type: str = "application/pdf",
) -> UploadFile:
    return UploadFile(
        filename=filename,
        file=BytesIO(content),
        headers=Headers({"content-type": content_type}),
    )


def make_service(
    *,
    session: Session,
    storage_root,
    max_upload_bytes: int = 1024,
    allowed_content_types: set[str] | None = None,
):
    uploads = get_uploads_module()
    return uploads.UploadService(
        session=session,
        storage=uploads.LocalFileStorage(root_dir=storage_root),
        max_upload_bytes=max_upload_bytes,
        allowed_content_types=allowed_content_types or {"application/pdf", "text/plain"},
    )


def count_uploads(session: Session) -> int:
    UploadedFile = get_uploaded_file_model()
    return len(session.exec(select(UploadedFile)).all())


# 测试上传服务成功路径：由服务端生成 storage_key、
# 写入原始文件、计算大小/校验值，并保存当前用户归属元数据。
def test_create_upload_stores_original_file_and_current_user_metadata(
    session: Session,
    user: User,
    tmp_path,
) -> None:
    UploadedFile = get_uploaded_file_model()
    content = b"lecture notes"
    service = make_service(session=session, storage_root=tmp_path)

    record = service.create_upload(
        current_user=user,
        file=make_upload_file(content, filename="../course-notes.pdf"),
    )

    stored_record = session.get(UploadedFile, record.id)
    assert stored_record is not None
    assert stored_record.owner_user_id == user.id
    assert stored_record.original_filename == "../course-notes.pdf"
    assert stored_record.content_type == "application/pdf"
    assert stored_record.byte_size == len(content)
    assert stored_record.checksum_sha256 == sha256(content).hexdigest()
    assert stored_record.status == "stored"
    assert stored_record.error_message is None

    storage_key = PurePosixPath(stored_record.storage_key)
    assert storage_key.parts[0] == "uploads"
    assert str(user.id) in stored_record.storage_key
    assert storage_key.name != "../course-notes.pdf"
    assert ".." not in storage_key.parts
    assert tmp_path.joinpath(*storage_key.parts).read_bytes() == content


# 测试部分浏览器把 .pptx 上报为旧 PowerPoint MIME 时，
# 只要部署已允许 PPTX 官方 MIME，上传服务仍接受该 .pptx 文件。
def test_create_upload_accepts_pptx_with_browser_legacy_powerpoint_mime(
    session: Session,
    user: User,
    tmp_path,
) -> None:
    service = make_service(
        session=session,
        storage_root=tmp_path,
        allowed_content_types={
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        },
    )

    record = service.create_upload(
        current_user=user,
        file=make_upload_file(
            b"pptx payload",
            filename="slides.pptx",
            content_type="application/vnd.ms-powerpoint",
        ),
    )

    assert record.original_filename == "slides.pptx"
    assert record.content_type == "application/vnd.ms-powerpoint"
    assert PurePosixPath(record.storage_key).name == "original.pptx"


def test_create_upload_rejects_legacy_powerpoint_mime_without_pptx_extension(
    session: Session,
    user: User,
    tmp_path,
) -> None:
    uploads = get_uploads_module()
    service = make_service(
        session=session,
        storage_root=tmp_path,
        allowed_content_types={
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        },
    )

    with pytest.raises(uploads.UploadValidationError, match="content type"):
        service.create_upload(
            current_user=user,
            file=make_upload_file(
                b"legacy ppt payload",
                filename="slides.ppt",
                content_type="application/vnd.ms-powerpoint",
            ),
        )


@pytest.mark.parametrize(
    ("content", "filename", "content_type", "max_upload_bytes", "expected_message"),
    [
        (b"", "empty.txt", "text/plain", 1024, "empty"),
        (b"1234", "too-large.txt", "text/plain", 3, "size"),
        (b"payload", "script.exe", "application/x-msdownload", 1024, "content type"),
    ],
)
# 测试空文件、超过配置大小限制、MIME 类型不在白名单内时校验失败，
# 并且不会创建元数据或写入文件。
def test_create_upload_rejects_invalid_files_without_metadata_or_storage(
    session: Session,
    user: User,
    tmp_path,
    content: bytes,
    filename: str,
    content_type: str,
    max_upload_bytes: int,
    expected_message: str,
) -> None:
    uploads = get_uploads_module()
    service = make_service(
        session=session,
        storage_root=tmp_path,
        max_upload_bytes=max_upload_bytes,
        allowed_content_types={"text/plain"},
    )

    with pytest.raises(uploads.UploadValidationError, match=expected_message):
        service.create_upload(
            current_user=user,
            file=make_upload_file(content, filename=filename, content_type=content_type),
        )

    assert count_uploads(session) == 0
    assert not any(path.is_file() for path in tmp_path.rglob("*"))


# 测试存储写入失败会作为上传存储错误暴露，
# 且不会留下指向缺失原始文件的成功元数据。
def test_create_upload_reports_storage_failure_without_success_metadata(
    session: Session,
    user: User,
    tmp_path,
) -> None:
    uploads = get_uploads_module()
    blocked_storage_root = tmp_path / "blocked-root"
    blocked_storage_root.write_text("not a directory", encoding="utf-8")
    service = make_service(session=session, storage_root=blocked_storage_root)

    with pytest.raises(uploads.UploadStorageError):
        service.create_upload(
            current_user=user,
            file=make_upload_file(b"content", content_type="application/pdf"),
        )

    assert count_uploads(session) == 0


# 测试元数据提交失败会清理已写入的文件，
# 避免数据库写入失败后留下孤立原始文件。
def test_create_upload_cleans_stored_file_when_metadata_commit_fails(
    monkeypatch,
    session: Session,
    user: User,
    tmp_path,
) -> None:
    uploads = get_uploads_module()
    service = make_service(session=session, storage_root=tmp_path)

    def fail_commit() -> None:
        raise RuntimeError("metadata failure")

    monkeypatch.setattr(session, "commit", fail_commit)

    with pytest.raises(uploads.UploadMetadataError, match="metadata"):
        service.create_upload(
            current_user=user,
            file=make_upload_file(b"content", content_type="application/pdf"),
        )

    assert not any(path.is_file() for path in tmp_path.rglob("*"))


# =========================================================================
# 日志记录测试（spec: Service 层日志记录 — uploads.py）
# GREEN 阶段：uploads.py 已接入日志，以下测试验证日志正确输出。
# =========================================================================


# 测试上传成功后应输出 INFO 级别日志，包含 upload_id、byte_size、checksum_sha256 字段。
def test_create_upload_logs_info_on_success(
    session: Session,
    user: User,
    tmp_path,
    caplog,
) -> None:
    caplog.set_level(logging.DEBUG, logger="app.services.uploads")
    content = b"lecture notes"
    service = make_service(session=session, storage_root=tmp_path)

    record = service.create_upload(
        current_user=user,
        file=make_upload_file(content, content_type="application/pdf"),
    )

    assert str(record.id) in caplog.text
    assert str(len(content)) in caplog.text
    assert any(r.levelname == "INFO" and "上传" in r.message for r in caplog.records)


# 测试 content type 校验失败时应输出 WARNING 级别日志，包含 content_type 和 allowed_types。
def test_create_upload_logs_warning_on_bad_content_type(
    session: Session,
    user: User,
    tmp_path,
    caplog,
) -> None:
    caplog.set_level(logging.DEBUG, logger="app.services.uploads")
    uploads = get_uploads_module()
    service = make_service(
        session=session,
        storage_root=tmp_path,
        allowed_content_types={"text/plain"},
    )

    with pytest.raises(uploads.UploadValidationError):
        service.create_upload(
            current_user=user,
            file=make_upload_file(
                b"payload", filename="script.exe", content_type="application/x-msdownload"
            ),
        )

    assert any(
        r.levelname == "WARNING" for r in caplog.records if r.message and "不支持" in r.message
    )


# 测试空文件上传时应输出 WARNING 级别日志，包含 upload_id。
def test_create_upload_logs_warning_on_empty_file(
    session: Session,
    user: User,
    tmp_path,
    caplog,
) -> None:
    caplog.set_level(logging.DEBUG, logger="app.services.uploads")
    uploads = get_uploads_module()
    service = make_service(
        session=session,
        storage_root=tmp_path,
        allowed_content_types={"text/plain"},
    )

    with pytest.raises(uploads.UploadValidationError, match="empty"):
        service.create_upload(
            current_user=user,
            file=make_upload_file(b"", filename="empty.txt", content_type="text/plain"),
        )

    assert any(r.levelname == "WARNING" for r in caplog.records if r.message and "空" in r.message)


# 测试存储写入失败时应输出 ERROR 级别日志，包含 storage_key 和异常信息。
def test_create_upload_logs_error_on_storage_failure(
    session: Session,
    user: User,
    tmp_path,
    caplog,
) -> None:
    caplog.set_level(logging.DEBUG, logger="app.services.uploads")
    uploads = get_uploads_module()
    blocked_storage_root = tmp_path / "blocked-root"
    blocked_storage_root.write_text("not a directory", encoding="utf-8")
    service = make_service(session=session, storage_root=blocked_storage_root)

    with pytest.raises(uploads.UploadStorageError):
        service.create_upload(
            current_user=user,
            file=make_upload_file(b"content", content_type="application/pdf"),
        )

    assert any(r.levelname == "ERROR" for r in caplog.records if r.message and "存储" in r.message)


# 测试元数据 commit 失败触发 rollback 时应输出 ERROR 级别日志，包含 upload_id 和异常信息。
def test_create_upload_logs_error_on_metadata_commit_failure(
    monkeypatch,
    session: Session,
    user: User,
    tmp_path,
    caplog,
) -> None:
    caplog.set_level(logging.DEBUG, logger="app.services.uploads")
    uploads = get_uploads_module()
    service = make_service(session=session, storage_root=tmp_path)

    def fail_commit() -> None:
        raise RuntimeError("metadata failure")

    monkeypatch.setattr(session, "commit", fail_commit)

    with pytest.raises(uploads.UploadMetadataError, match="metadata"):
        service.create_upload(
            current_user=user,
            file=make_upload_file(b"content", content_type="application/pdf"),
        )

    assert any(r.levelname == "ERROR" for r in caplog.records if r.message and "回滚" in r.message)
