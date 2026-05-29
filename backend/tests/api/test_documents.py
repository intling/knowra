from collections.abc import Generator
from contextlib import suppress
from datetime import UTC, datetime
from importlib import import_module
from pathlib import PurePosixPath
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import get_settings
from app.db.session import get_session
from app.main import app
from app.models.uploaded_file import UploadedFile
from app.models.user import User
from app.services.users import DEFAULT_USER_ID

# 本文件验证 documents API 的创建、读取、冲突处理、权限隔离和错误映射。

DOCUMENT_FIELDS = {
    "id",
    "owner_user_id",
    "uploaded_file_id",
    "title",
    "source_content_type",
    "parser_name",
    "parser_version",
    "chunker_name",
    "chunker_version",
    "tokenizer_name",
    "tokenizer_version",
    "status",
    "chunk_count",
    "total_chars",
    "content_sha256",
    "metadata_json",
    "error_message",
    "deleted_at",
    "created_at",
    "updated_at",
    "source_file",
}
CHUNK_FIELDS = {
    "id",
    "document_id",
    "owner_user_id",
    "chunk_index",
    "content",
    "content_sha256",
    "char_start",
    "char_end",
    "token_count",
    "source_locator_json",
    "metadata_json",
    "created_at",
    "updated_at",
}


@pytest.fixture
def session() -> Generator[Session]:
    with suppress(ModuleNotFoundError):
        import_module("app.models.document")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as test_session:
        yield test_session


@pytest.fixture
def documents_client(
    monkeypatch,
    session: Session,
    tmp_path,
) -> Generator[TestClient]:
    monkeypatch.setenv("UPLOAD_STORAGE_DIR", str(tmp_path))
    get_settings.cache_clear()

    def override_get_session() -> Generator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def seed_user(session: Session, *, user_id: UUID = DEFAULT_USER_ID) -> User:
    created_at = datetime(2026, 5, 25, tzinfo=UTC)
    user = User(
        id=user_id,
        display_name="Default User",
        status="active",
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def seed_upload(
    session: Session,
    storage_root,
    *,
    owner_user_id: UUID = DEFAULT_USER_ID,
    filename: str = "course-notes.txt",
    content_type: str | None = "text/plain",
    status: str = "stored",
    content: bytes = b"course notes about semantic retrieval",
) -> UploadedFile:
    upload_id = uuid4()
    suffix = PurePosixPath(filename).suffix or ".bin"
    storage_key = f"uploads/{owner_user_id}/{upload_id}/original{suffix}"
    path = storage_root.joinpath(*PurePosixPath(storage_key).parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)

    upload = UploadedFile(
        id=upload_id,
        owner_user_id=owner_user_id,
        original_filename=filename,
        content_type=content_type,
        byte_size=len(content),
        storage_key=storage_key,
        checksum_sha256=None,
        status=status,
        error_message=None,
        created_at=datetime(2026, 5, 25, tzinfo=UTC),
        updated_at=datetime(2026, 5, 25, tzinfo=UTC),
    )
    session.add(upload)
    session.commit()
    session.refresh(upload)
    return upload


def count_documents(session: Session) -> int:
    try:
        Document = import_module("app.models.document").Document
    except ModuleNotFoundError:
        return 0

    return len(session.exec(select(Document)).all())


def seed_document(
    session: Session,
    upload: UploadedFile,
    *,
    owner_user_id: UUID = DEFAULT_USER_ID,
    status: str = "parsed",
    chunk_count: int = 1,
):
    Document = import_module("app.models.document").Document
    document = Document(
        owner_user_id=owner_user_id,
        uploaded_file_id=upload.id,
        title=upload.original_filename,
        source_content_type=upload.content_type,
        parser_name="test-parser",
        parser_version="test",
        chunker_name="test-chunker",
        chunker_version="test",
        tokenizer_name="test-tokenizer",
        tokenizer_version="test",
        status=status,
        chunk_count=chunk_count,
        total_chars=12 if status == "parsed" else 0,
        content_sha256="a" * 64 if status == "parsed" else None,
        metadata_json={},
        error_message="PDF requires OCR" if status == "failed" else None,
        created_at=datetime(2026, 5, 25, tzinfo=UTC),
        updated_at=datetime(2026, 5, 25, tzinfo=UTC),
    )
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def seed_chunk(session: Session, document) -> None:
    DocumentChunk = import_module("app.models.document").DocumentChunk
    chunk = DocumentChunk(
        document_id=document.id,
        owner_user_id=document.owner_user_id,
        chunk_index=0,
        content="seeded chunk",
        content_sha256="b" * 64,
        char_start=0,
        char_end=12,
        token_count=2,
        source_locator_json={"line_start": 1},
        metadata_json={},
        created_at=datetime(2026, 5, 25, tzinfo=UTC),
        updated_at=datetime(2026, 5, 25, tzinfo=UTC),
    )
    session.add(chunk)
    session.commit()


# 测试提交已存储上传文件后会创建 parsed 文档，并可通过列表、详情和分块接口读取。
def test_post_documents_creates_parsed_document_and_read_apis(
    documents_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    seed_user(session)
    upload = seed_upload(session, tmp_path)

    response = documents_client.post(
        "/api/documents",
        json={"uploaded_file_id": str(upload.id)},
    )

    assert response.status_code == 201
    document = response.json()
    assert set(document) == DOCUMENT_FIELDS
    assert document["owner_user_id"] == str(DEFAULT_USER_ID)
    assert document["uploaded_file_id"] == str(upload.id)
    assert document["title"] == "course-notes.txt"
    assert document["status"] == "parsed"
    assert document["chunk_count"] > 0
    assert document["error_message"] is None
    assert document["source_file"]["original_filename"] == "course-notes.txt"

    list_response = documents_client.get("/api/documents")
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [document["id"]]

    detail_response = documents_client.get(f"/api/documents/{document['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == document["id"]

    chunks_response = documents_client.get(f"/api/documents/{document['id']}/chunks")
    assert chunks_response.status_code == 200
    chunks = chunks_response.json()
    assert len(chunks) == document["chunk_count"]
    assert set(chunks[0]) == CHUNK_FIELDS
    assert chunks[0]["chunk_index"] == 0
    assert "semantic retrieval" in chunks[0]["content"]


# 测试同一上传文件重复创建文档时返回 409，并携带已存在的文档信息。
def test_post_documents_returns_conflict_with_existing_document(
    documents_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    seed_user(session)
    upload = seed_upload(session, tmp_path)

    first_response = documents_client.post(
        "/api/documents",
        json={"uploaded_file_id": str(upload.id)},
    )
    second_response = documents_client.post(
        "/api/documents",
        json={"uploaded_file_id": str(upload.id)},
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 409
    payload = second_response.json()
    assert payload["existing_document"]["id"] == first_response.json()["id"]
    assert payload["existing_document"]["uploaded_file_id"] == str(upload.id)
    assert count_documents(session) == 1


# 测试当前用户不能用其他用户的上传文件创建文档，接口以 404 隐藏跨用户资源。
def test_post_documents_returns_404_without_leaking_other_users_uploads(
    documents_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    seed_user(session)
    other_user_id = uuid4()
    seed_user(session, user_id=other_user_id)
    other_upload = seed_upload(session, tmp_path, owner_user_id=other_user_id)

    response = documents_client.post(
        "/api/documents",
        json={"uploaded_file_id": str(other_upload.id)},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Uploaded file not found"}
    assert count_documents(session) == 0


# 测试非 stored 状态的上传文件不会进入文档处理，避免处理失败或未就绪的上传。
def test_post_documents_rejects_uploads_that_are_not_stored(
    documents_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    seed_user(session)
    upload = seed_upload(session, tmp_path, status="failed")

    response = documents_client.post(
        "/api/documents",
        json={"uploaded_file_id": str(upload.id)},
    )

    assert response.status_code == 409
    assert "stored" in response.text
    assert count_documents(session) == 0


# 测试不支持的文件类型返回 415，并记录 failed 文档供前端展示失败原因。
def test_post_documents_returns_415_for_unsupported_document_types(
    documents_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    seed_user(session)
    upload = seed_upload(
        session,
        tmp_path,
        filename="archive.zip",
        content_type="application/zip",
        content=b"zip bytes",
    )

    response = documents_client.post(
        "/api/documents",
        json={"uploaded_file_id": str(upload.id)},
    )

    assert response.status_code == 415
    assert "Unsupported" in response.text

    list_response = documents_client.get("/api/documents")
    assert list_response.status_code == 200
    failed_documents = [item for item in list_response.json() if item["status"] == "failed"]
    assert len(failed_documents) == 1
    assert "Unsupported" in failed_documents[0]["error_message"]


# 测试文档详情和分块读取同样执行用户隔离，不能读取其他用户的文档。
def test_document_detail_and_chunks_hide_other_users_documents(
    documents_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    seed_user(session)
    other_user_id = uuid4()
    seed_user(session, user_id=other_user_id)
    other_upload = seed_upload(session, tmp_path, owner_user_id=other_user_id)
    other_document = seed_document(
        session,
        other_upload,
        owner_user_id=other_user_id,
        status="parsed",
    )
    seed_chunk(session, other_document)

    detail_response = documents_client.get(f"/api/documents/{other_document.id}")
    chunks_response = documents_client.get(f"/api/documents/{other_document.id}/chunks")

    assert detail_response.status_code == 404
    assert chunks_response.status_code == 404


# 测试 failed 文档没有可用分块时，分块接口返回空列表而不是错误。
def test_failed_document_chunks_return_empty_list(
    documents_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    seed_user(session)
    upload = seed_upload(session, tmp_path, filename="scan.pdf", content_type="application/pdf")
    document = seed_document(session, upload, status="failed", chunk_count=0)

    chunks_response = documents_client.get(f"/api/documents/{document.id}/chunks")

    assert chunks_response.status_code == 200
    assert chunks_response.json() == []


# 测试文档处理服务抛出未预期错误时，API 映射为统一的 500 响应。
def test_post_documents_maps_unexpected_processing_errors_to_500(
    monkeypatch,
    documents_client: TestClient,
    session: Session,
    tmp_path,
) -> None:
    seed_user(session)
    upload = seed_upload(session, tmp_path)
    documents_routes = import_module("app.api.routes.documents")
    processing = import_module("app.services.document_processing")

    class BrokenDocumentProcessingService:
        def __init__(self, **kwargs):
            pass

        def create_document(self, *, current_user, uploaded_file_id):
            raise processing.DocumentProcessingServiceError("database write failed")

    monkeypatch.setattr(
        documents_routes,
        "DocumentProcessingService",
        BrokenDocumentProcessingService,
    )

    response = documents_client.post(
        "/api/documents",
        json={"uploaded_file_id": str(upload.id)},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Failed to process document"}
