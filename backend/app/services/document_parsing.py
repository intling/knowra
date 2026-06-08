from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlmodel import Session, select

from app.models.document_parsing import DocumentParseJob
from app.models.uploaded_file import UploadedFile
from app.models.user import User, utc_now
from app.services.document_parser import (
    DocumentFormatPolicy,
)
from app.services.document_parser import (
    UnsupportedDocumentFormatError as ParserUnsupportedDocumentFormatError,
)
from app.services.uploads import LocalFileStorage, UploadStorageError

UnsupportedDocumentFormatError = ParserUnsupportedDocumentFormatError


class DocumentParsingDisabledError(Exception):
    pass


class DocumentParseNotFoundError(Exception):
    pass


class DocumentParseTooLargeError(Exception):
    pass


@dataclass(frozen=True)
class DocumentParseConflictError(Exception):
    job: DocumentParseJob
    uploaded_file: UploadedFile


class DocumentParseService:
    def __init__(
        self,
        *,
        session: Session,
        upload_storage: LocalFileStorage,
        document_parse_enabled: bool,
        max_parse_bytes: int,
        max_parse_pages: int,
        allowed_content_types: set[str],
        allowed_extensions: set[str],
    ) -> None:
        self.session = session
        self.upload_storage = upload_storage
        self.document_parse_enabled = document_parse_enabled
        self.max_parse_bytes = max_parse_bytes
        self.max_parse_pages = max_parse_pages
        self.format_policy = DocumentFormatPolicy(
            allowed_content_types=allowed_content_types,
            allowed_extensions={extension.lower() for extension in allowed_extensions},
        )

    def create_parse_job(self, *, current_user: User, upload_id: UUID) -> DocumentParseJob:
        if not self.document_parse_enabled:
            raise DocumentParsingDisabledError

        uploaded_file = self._get_owned_upload(current_user=current_user, upload_id=upload_id)
        existing_job = self._get_running_job(uploaded_file_id=uploaded_file.id)
        if existing_job is not None:
            raise DocumentParseConflictError(job=existing_job, uploaded_file=uploaded_file)

        if uploaded_file.byte_size > self.max_parse_bytes:
            raise DocumentParseTooLargeError("File size exceeds document_parse_max_bytes")

        path = self._path_for_upload(uploaded_file)
        if not path.is_file():
            raise DocumentParseNotFoundError("Uploaded file content not found")

        self.format_policy.validate(
            path,
            original_filename=uploaded_file.original_filename,
            content_type=uploaded_file.content_type,
        )

        now = utc_now()
        job = DocumentParseJob(
            uploaded_file_id=uploaded_file.id,
            owner_user_id=current_user.id,
            status="queued",
            parser_name="docling",
            created_at=now,
            updated_at=now,
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job

    def _get_owned_upload(self, *, current_user: User, upload_id: UUID) -> UploadedFile:
        statement = select(UploadedFile).where(
            UploadedFile.id == upload_id,
            UploadedFile.owner_user_id == current_user.id,
            UploadedFile.status == "stored",
            UploadedFile.deleted_at.is_(None),
        )
        uploaded_file = self.session.exec(statement).first()
        if uploaded_file is None:
            raise DocumentParseNotFoundError("Upload not found")

        return uploaded_file

    def _get_running_job(self, *, uploaded_file_id: UUID) -> DocumentParseJob | None:
        statement = select(DocumentParseJob).where(
            DocumentParseJob.uploaded_file_id == uploaded_file_id,
            DocumentParseJob.status.in_(["queued", "running"]),
        )
        return self.session.exec(statement).first()

    def _path_for_upload(self, uploaded_file: UploadedFile) -> Path:
        try:
            return self.upload_storage.path_for(uploaded_file.storage_key)
        except UploadStorageError as exc:
            raise DocumentParseNotFoundError("Uploaded file content not found") from exc
