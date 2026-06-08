from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from fastapi import BackgroundTasks
from sqlmodel import Session

from app.core.config import get_settings
from app.db.session import engine
from app.models.document_parsing import DocumentParseJob, DocumentSegment, ParsedDocument
from app.models.uploaded_file import UploadedFile
from app.models.user import utc_now
from app.services.document_parse_storage import ParsedArtifactStorage
from app.services.document_parser import (
    DoclingParserAdapter,
    DocumentFormatPolicy,
    DocumentParseError,
    ParsedDocumentPayload,
    ensure_parsed_payload_has_text_content,
)
from app.services.uploads import LocalFileStorage

SessionFactory = Callable[[], Generator[Session]]


class BackgroundTasksParseJobDispatcher:
    def __init__(self, background_tasks: BackgroundTasks) -> None:
        self.background_tasks = background_tasks

    def enqueue(self, job_id) -> None:
        self.background_tasks.add_task(run_parse_job, job_id)


def run_parse_job(
    job_id,
    *,
    session_factory: SessionFactory | None = None,
    parser: object | None = None,
    upload_storage_root: str | Path | None = None,
    artifact_storage_root: str | Path | None = None,
) -> None:
    settings = get_settings()
    session_context = session_factory or default_session_factory

    with session_context() as session:
        job = session.get(DocumentParseJob, coerce_uuid(job_id))
        if job is None or job.status != "queued":
            return

        job.status = "running"
        job.attempt_count += 1
        job.started_at = utc_now()
        job.updated_at = utc_now()
        session.add(job)
        session.commit()
        session.refresh(job)

        try:
            uploaded_file = session.get(UploadedFile, job.uploaded_file_id)
            if uploaded_file is None:
                raise DocumentParseError("Uploaded file not found")

            upload_storage = LocalFileStorage(upload_storage_root or settings.upload_storage_dir)
            source_path = upload_storage.path_for(uploaded_file.storage_key)
            document_format = DocumentFormatPolicy(
                allowed_content_types=set(settings.document_parse_allowed_content_types),
                allowed_extensions=set(settings.document_parse_allowed_extensions),
            ).validate(
                source_path,
                original_filename=uploaded_file.original_filename,
                content_type=uploaded_file.content_type,
            )
            active_parser = parser or DoclingParserAdapter(
                ocr_enabled=settings.document_parse_ocr_enabled,
                max_pages=settings.document_parse_max_pages,
                docling_cache_dir=settings.document_parse_docling_cache_dir,
            )
            payload = active_parser.parse(source_path, document_format=document_format)
            ensure_parsed_payload_has_text_content(payload)
            save_parse_result(
                session=session,
                job=job,
                uploaded_file=uploaded_file,
                payload=payload,
                artifact_storage=ParsedArtifactStorage(
                    artifact_storage_root or settings.document_parse_artifact_dir
                ),
            )
            job.status = "succeeded"
            job.error_code = None
            job.error_message = None
        except Exception as exc:
            job.status = "failed"
            job.error_code = "parse_failed"
            job.error_message = str(exc)
        finally:
            job.finished_at = utc_now()
            job.updated_at = utc_now()
            session.add(job)
            session.commit()


def save_parse_result(
    *,
    session: Session,
    job: DocumentParseJob,
    uploaded_file: UploadedFile,
    payload: ParsedDocumentPayload,
    artifact_storage: ParsedArtifactStorage,
) -> ParsedDocument:
    keys = artifact_storage.save(
        owner_user_id=job.owner_user_id,
        uploaded_file_id=job.uploaded_file_id,
        parse_job_id=job.id,
        payload=payload,
    )
    parsed_document = ParsedDocument(
        uploaded_file_id=uploaded_file.id,
        parse_job_id=job.id,
        owner_user_id=job.owner_user_id,
        source_checksum_sha256=uploaded_file.checksum_sha256,
        markdown_storage_key=keys.markdown_storage_key,
        text_storage_key=keys.text_storage_key,
        docling_json_storage_key=keys.docling_json_storage_key,
        title=payload.title,
        page_count=payload.page_count,
        metadata_json=payload.metadata,
    )
    session.add(parsed_document)
    session.flush()

    for segment in payload.segments:
        session.add(
            DocumentSegment(
                parsed_document_id=parsed_document.id,
                owner_user_id=job.owner_user_id,
                sequence_index=segment.sequence_index,
                segment_type=segment.segment_type,
                page_no=segment.page_no,
                heading_path=segment.heading_path,
                text=segment.text,
                metadata_json=segment.metadata,
            )
        )

    session.commit()
    session.refresh(parsed_document)
    return parsed_document


@contextmanager
def default_session_factory() -> Generator[Session]:
    with Session(engine) as session:
        yield session


def coerce_uuid(value) -> UUID:
    if isinstance(value, UUID):
        return value

    return UUID(str(value))
