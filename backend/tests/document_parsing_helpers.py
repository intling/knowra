from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from sqlmodel import Session

from app.models.uploaded_file import UploadedFile
from app.models.user import User

MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R >>\nendobj\n"
    b"%%EOF\n"
)


@dataclass(frozen=True)
class ParsedPayloadFactory:
    markdown: str = "# Parsed Notes\n\nBody"
    text: str = "Parsed Notes\nBody"
    page_count: int = 1

    def make(self):
        parser = __import__("app.services.document_parser", fromlist=["ParsedDocumentPayload"])
        return parser.ParsedDocumentPayload(
            markdown=self.markdown,
            text=self.text,
            docling_json={"title": "Parsed Notes", "page_count": self.page_count},
            title="Parsed Notes",
            page_count=self.page_count,
            metadata={"source": "fixture"},
            segments=[
                parser.ParsedSegmentPayload(
                    sequence_index=0,
                    segment_type="paragraph",
                    page_no=1,
                    heading_path=["Parsed Notes"],
                    text="Body",
                    metadata={"docling_ref": "#/texts/0"},
                )
            ],
        )


class SessionFactory:
    def __init__(self, session: Session) -> None:
        self.session = session

    @contextmanager
    def __call__(self) -> Generator[Session]:
        yield self.session


def make_user(session: Session, *, display_name: str = "Parse Owner") -> User:
    created_at = datetime(2026, 6, 5, tzinfo=UTC)
    user = User(
        display_name=display_name,
        status="active",
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def make_uploaded_file(
    session: Session,
    storage_root: Path,
    user: User,
    *,
    content: bytes = MINIMAL_PDF,
    original_filename: str = "notes.pdf",
    content_type: str = "application/pdf",
    status: str = "stored",
    deleted: bool = False,
    upload_id: UUID | None = None,
) -> UploadedFile:
    upload_id = upload_id or uuid4()
    storage_key = f"uploads/{user.id}/{upload_id}/original{Path(original_filename).suffix}"
    path = storage_root.joinpath(*PurePosixPath(storage_key).parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    created_at = datetime(2026, 6, 5, tzinfo=UTC)

    record = UploadedFile(
        id=upload_id,
        owner_user_id=user.id,
        original_filename=original_filename,
        content_type=content_type,
        byte_size=len(content),
        storage_key=storage_key,
        checksum_sha256=sha256(content).hexdigest(),
        status=status,
        deleted_at=created_at if deleted else None,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def write_minimal_pdf(path: Path) -> Path:
    path.write_bytes(MINIMAL_PDF)
    return path


def write_text_fixture(path: Path, content: str = "Lecture notes\n") -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def write_minimal_docx(path: Path) -> Path:
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types></Types>")
        archive.writestr("word/document.xml", "<w:document></w:document>")
    return path


def write_minimal_pptx(path: Path) -> Path:
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types></Types>")
        archive.writestr("ppt/presentation.xml", "<p:presentation></p:presentation>")
    return path
