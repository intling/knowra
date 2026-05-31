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
