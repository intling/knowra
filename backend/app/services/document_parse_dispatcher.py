from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress
from pathlib import Path
from uuid import UUID

from fastapi import BackgroundTasks
from sqlmodel import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import engine
from app.models.document_parsing import DocumentParseJob, DocumentSegment, ParsedDocument
from app.models.uploaded_file import UploadedFile
from app.models.user import utc_now
from app.services.document_chunk_storage import ChunkArtifactStorage
from app.services.document_chunker import DoclingChunkerAdapter, DocumentChunkingConfig
from app.services.document_chunking import DocumentChunkingService
from app.services.document_parse_storage import ParsedArtifactStorage
from app.services.document_parser import (
    DoclingParserAdapter,
    DocumentFormat,
    DocumentFormatPolicy,
    DocumentParseError,
    ParsedDocumentPayload,
    ParsedDocumentResult,
    ensure_parsed_payload_has_text_content,
)
from app.services.uploads import LocalFileStorage

logger = get_logger(__name__)

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
    document_chunking_enabled: bool | None = None,
    chunking_service: object | None = None,
    model_readiness: object | None = None,
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

        logger.info("Parse started", job_id=str(job.id))

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
            ensure_docling_models_ready(
                document_format=document_format,
                model_readiness=model_readiness,
            )
            active_parser = parser or DoclingParserAdapter(
                ocr_enabled=settings.document_parse_ocr_enabled,
                max_pages=settings.document_parse_max_pages,
                docling_artifact_dir=get_docling_artifact_dir(settings, model_readiness),
                converter=get_docling_converter(model_readiness),
            )
            parse_result = normalize_parse_result(
                active_parser.parse(source_path, document_format=document_format)
            )
            payload = parse_result.persistent_payload
            ensure_parsed_payload_has_text_content(payload)
            parsed_document = save_parse_result(
                session=session,
                job=job,
                uploaded_file=uploaded_file,
                payload=payload,
                artifact_storage=ParsedArtifactStorage(
                    artifact_storage_root or settings.document_parse_artifact_dir
                ),
            )
            mark_parse_job_succeeded(session=session, job=job)
            logger.info(
                "Parse succeeded",
                job_id=str(job.id),
                pages=payload.page_count or 0,
                segments=len(payload.segments),
            )
            should_chunk = (
                settings.document_chunking_enabled
                if document_chunking_enabled is None
                else document_chunking_enabled
            )
            if should_chunk:
                with suppress(Exception):
                    logger.info("Auto-chunking started", parse_job_id=str(job.id))
                    service = chunking_service or make_document_chunking_service(
                        session=session,
                        settings=settings,
                        upload_storage_root=upload_storage_root,
                        model_readiness=model_readiness,
                    )
                    chunk_job = service.run_initial_chunking(
                        parsed_document=parsed_document,
                        transient_docling_document=parse_result.transient_docling_document,
                    )
                    logger.info(
                        "Auto-chunking succeeded",
                        parse_job_id=str(job.id),
                        chunk_job_id=str(chunk_job.id),
                        chunks=chunk_job.chunk_count or 0,
                    )
        except DocumentModelUnavailableError as exc:
            logger.error(
                "Parse failed",
                job_id=str(job.id),
                reason="model_unavailable",
                error=str(exc),
                exc_info=True,
            )
            job.status = "failed"
            job.error_code = "model_unavailable"
            job.error_message = str(exc)
            job.finished_at = utc_now()
            job.updated_at = utc_now()
            session.add(job)
            session.commit()
        except Exception as exc:
            logger.error(
                "Parse failed",
                job_id=str(job.id),
                error=str(exc),
                exc_info=True,
            )
            job.status = "failed"
            job.error_code = "parse_failed"
            job.error_message = str(exc)
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


def mark_parse_job_succeeded(*, session: Session, job: DocumentParseJob) -> None:
    job.status = "succeeded"
    job.error_code = None
    job.error_message = None
    job.finished_at = utc_now()
    job.updated_at = utc_now()
    session.add(job)
    session.commit()
    session.refresh(job)


def normalize_parse_result(
    result: ParsedDocumentPayload | ParsedDocumentResult,
) -> ParsedDocumentResult:
    if isinstance(result, ParsedDocumentResult):
        return result

    return ParsedDocumentResult(
        persistent_payload=result,
        transient_docling_document=getattr(result, "transient_docling_document", None),
    )


class DocumentModelUnavailableError(DocumentParseError):
    pass


def ensure_docling_models_ready(
    *,
    document_format: DocumentFormat,
    model_readiness: object | None,
) -> None:
    if document_format in {DocumentFormat.TXT, DocumentFormat.MARKDOWN}:
        return
    docling = getattr(model_readiness, "docling", None)
    if docling is None or getattr(docling, "status", "ready") == "ready":
        return
    if getattr(docling, "status", "ready") == "skipped":
        return
    if getattr(docling, "status", "ready") == "loading":
        raise DocumentModelUnavailableError("Document models are still loading")
    missing = ", ".join(getattr(docling, "missing_models", []) or [])
    detail = (
        f"Document models are unavailable: {missing}"
        if missing
        else "Document models are unavailable"
    )
    raise DocumentModelUnavailableError(detail)


def get_docling_artifact_dir(settings, model_readiness: object | None) -> str:
    docling = getattr(model_readiness, "docling", None)
    artifact_dir = getattr(docling, "artifact_dir", None)
    if artifact_dir:
        return str(artifact_dir)
    return settings.document_model_docling_artifact_dir


def get_docling_converter(model_readiness: object | None) -> object | None:
    docling = getattr(model_readiness, "docling", None)
    return getattr(docling, "resource", None)


def make_document_chunking_service(
    *,
    session: Session,
    settings,
    upload_storage_root: str | Path | None = None,
    model_readiness: object | None = None,
) -> DocumentChunkingService:
    config = DocumentChunkingConfig(
        tokenizer_model=settings.document_model_tokenizer_name,
        max_tokens=settings.document_chunk_max_tokens,
        merge_peers=settings.document_chunk_merge_peers,
        repeat_table_header=settings.document_chunk_repeat_table_header,
        inline_text_max_bytes=settings.document_chunk_inline_text_max_bytes,
        tokenizer_cache_dir=settings.document_model_tokenizer_cache_dir,
    )
    return DocumentChunkingService(
        session=session,
        chunker=DoclingChunkerAdapter(config=config, model_readiness=model_readiness),
        artifact_storage=ChunkArtifactStorage(settings.document_chunk_artifact_storage_dir),
        config=config,
        upload_storage=LocalFileStorage(upload_storage_root or settings.upload_storage_dir),
        model_readiness=model_readiness,
    )


@contextmanager
def default_session_factory() -> Generator[Session]:
    with Session(engine) as session:
        yield session


def coerce_uuid(value) -> UUID:
    if isinstance(value, UUID):
        return value

    return UUID(str(value))
