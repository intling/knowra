from collections.abc import Generator
from contextlib import suppress
from importlib import import_module

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.user import User
from tests.document_parsing_helpers import MINIMAL_PDF, make_uploaded_file, make_user


def get_parsing_module():
    return import_module("app.services.document_parsing")


def get_models_module():
    return import_module("app.models.document_parsing")


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
def user(session: Session) -> User:
    return make_user(session)


def make_service(
    *,
    session: Session,
    storage_root,
    max_parse_bytes: int = 50 * 1024 * 1024,
    max_parse_pages: int = 100,
    allowed_content_types: set[str] | None = None,
    allowed_extensions: set[str] | None = None,
    enabled: bool = True,
):
    parsing = get_parsing_module()
    uploads = import_module("app.services.uploads")
    return parsing.DocumentParseService(
        session=session,
        upload_storage=uploads.LocalFileStorage(storage_root),
        document_parse_enabled=enabled,
        max_parse_bytes=max_parse_bytes,
        max_parse_pages=max_parse_pages,
        allowed_content_types=allowed_content_types or {"application/pdf", "text/plain"},
        allowed_extensions=allowed_extensions or {".pdf", ".txt"},
    )


def count_jobs(session: Session) -> int:
    models = get_models_module()
    return len(session.exec(select(models.DocumentParseJob)).all())


# 测试当前用户只能为自己已存储且未删除的上传文件创建 queued 解析作业。
def test_create_parse_job_for_owned_upload(session: Session, user: User, tmp_path) -> None:
    service = make_service(session=session, storage_root=tmp_path)
    upload = make_uploaded_file(session, tmp_path, user)

    job = service.create_parse_job(current_user=user, upload_id=upload.id)

    assert job.uploaded_file_id == upload.id
    assert job.owner_user_id == user.id
    assert job.status == "queued"
    assert job.parser_name == "docling"
    assert count_jobs(session) == 1


@pytest.mark.parametrize("deleted", [False, True])
# 测试不存在、非归属或已删除上传文件不会创建解析作业。
def test_create_parse_job_rejects_missing_foreign_or_deleted_uploads(
    session: Session,
    user: User,
    tmp_path,
    deleted: bool,
) -> None:
    parsing = get_parsing_module()
    other_user = make_user(session, display_name="Other Owner")
    upload = make_uploaded_file(session, tmp_path, other_user, deleted=deleted)
    service = make_service(session=session, storage_root=tmp_path)

    with pytest.raises(parsing.DocumentParseNotFoundError):
        service.create_parse_job(current_user=user, upload_id=upload.id)

    with pytest.raises(parsing.DocumentParseNotFoundError):
        service.create_parse_job(current_user=user, upload_id=other_user.id)

    assert count_jobs(session) == 0


# 测试解析入口会执行独立格式策略，不因文件已上传就跳过类型校验。
def test_create_parse_job_rejects_unsupported_document_type(
    session: Session,
    user: User,
    tmp_path,
) -> None:
    parsing = get_parsing_module()
    upload = make_uploaded_file(
        session,
        tmp_path,
        user,
        content=b"MZ executable",
        original_filename="malware.exe",
        content_type="application/x-msdownload",
    )
    service = make_service(session=session, storage_root=tmp_path)

    with pytest.raises(parsing.UnsupportedDocumentFormatError, match="Unsupported"):
        service.create_parse_job(current_user=user, upload_id=upload.id)

    assert count_jobs(session) == 0


# 测试解析服务使用配置中的最大解析字节数拒绝超限文件。
def test_create_parse_job_rejects_file_over_parse_size_limit(
    session: Session,
    user: User,
    tmp_path,
) -> None:
    parsing = get_parsing_module()
    upload = make_uploaded_file(
        session,
        tmp_path,
        user,
        content=MINIMAL_PDF,
        original_filename="large.pdf",
        content_type="application/pdf",
    )
    service = make_service(session=session, storage_root=tmp_path, max_parse_bytes=4)

    with pytest.raises(parsing.DocumentParseTooLargeError, match="document_parse_max_bytes"):
        service.create_parse_job(current_user=user, upload_id=upload.id)

    assert count_jobs(session) == 0


@pytest.mark.parametrize("status", ["queued", "running"])
# 测试重复触发运行中作业会返回冲突上下文，而不是创建第二个并发作业。
def test_create_parse_job_returns_conflict_with_document_info_for_running_job(
    session: Session,
    user: User,
    tmp_path,
    status: str,
) -> None:
    parsing = get_parsing_module()
    models = get_models_module()
    upload = make_uploaded_file(session, tmp_path, user, original_filename="active.pdf")
    existing = models.DocumentParseJob(
        uploaded_file_id=upload.id,
        owner_user_id=user.id,
        status=status,
        parser_name="docling",
    )
    session.add(existing)
    session.commit()
    session.refresh(existing)
    service = make_service(session=session, storage_root=tmp_path)

    with pytest.raises(parsing.DocumentParseConflictError) as error:
        service.create_parse_job(current_user=user, upload_id=upload.id)

    assert error.value.job.id == existing.id
    assert error.value.uploaded_file.id == upload.id
    assert error.value.uploaded_file.original_filename == "active.pdf"
    assert count_jobs(session) == 1


# 测试解析开关关闭时拒绝创建作业。
def test_create_parse_job_rejects_when_document_parsing_disabled(
    session: Session,
    user: User,
    tmp_path,
) -> None:
    parsing = get_parsing_module()
    upload = make_uploaded_file(session, tmp_path, user)
    service = make_service(session=session, storage_root=tmp_path, enabled=False)

    with pytest.raises(parsing.DocumentParsingDisabledError):
        service.create_parse_job(current_user=user, upload_id=upload.id)

    assert count_jobs(session) == 0
