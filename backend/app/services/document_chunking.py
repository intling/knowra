from app.core.logging import get_logger
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlmodel import Session, col, select

from app.models.document_chunking import DocumentChunk, DocumentChunkJob, DocumentChunkJobStatus
from app.models.document_parsing import ParsedDocument
from app.models.uploaded_file import UploadedFile
from app.models.user import User, utc_now
from app.services.document_chunk_storage import ChunkArtifactStorage
from app.services.document_chunker import DocumentChunkingConfig, DocumentChunkingError
from app.services.uploads import LocalFileStorage, UploadStorageError

logger = get_logger(__name__)


class DocumentChunkNotFoundError(Exception):
    pass


class DocumentChunkOriginalFileUnavailableError(Exception):
    pass


@dataclass(frozen=True)
class DocumentChunkConflictError(Exception):
    job: DocumentChunkJob


class DocumentChunkingService:
    def __init__(
        self,
        *,
        session: Session,
        chunker: object,
        artifact_storage: ChunkArtifactStorage,
        config: DocumentChunkingConfig,
        upload_storage: LocalFileStorage | None = None,
    ) -> None:
        self.session = session
        self.chunker = chunker
        self.artifact_storage = artifact_storage
        self.config = config
        self.upload_storage = upload_storage

    def run_initial_chunking(
        self,
        *,
        parsed_document: ParsedDocument,
        transient_docling_document: object | None,
    ) -> DocumentChunkJob:
        job = self._create_job(parsed_document=parsed_document)
        return self._run_job(
            job=job,
            parsed_document=parsed_document,
            transient_docling_document=transient_docling_document,
            supersede_previous=False,
        )

    def rechunk(
        self,
        *,
        parsed_document_id: UUID,
        current_user: User,
        parser: object | None = None,
    ) -> DocumentChunkJob:
        parsed_document = self._get_owned_parsed_document(
            parsed_document_id=parsed_document_id,
            owner_user_id=current_user.id,
        )
        running_job = self._get_running_job(parsed_document_id=parsed_document.id)
        if running_job is not None:
            raise DocumentChunkConflictError(job=running_job)

        if parser is None and self.upload_storage is None:
            raise DocumentChunkOriginalFileUnavailableError("Original uploaded file is unavailable")

        document = self._parse_original_file(parsed_document=parsed_document, parser=parser)
        job = self._create_job(parsed_document=parsed_document)
        return self._run_job(
            job=job,
            parsed_document=parsed_document,
            transient_docling_document=document,
            supersede_previous=True,
        )

    def _create_job(self, *, parsed_document: ParsedDocument) -> DocumentChunkJob:
        now = utc_now()
        job = DocumentChunkJob(
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status=DocumentChunkJobStatus.QUEUED.value,
            chunker_name="docling_hybrid",
            chunker_version="docling-core",
            chunk_config_json=self.config.snapshot(),
            created_at=now,
            updated_at=now,
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job

    def _run_job(
        self,
        *,
        job: DocumentChunkJob,
        parsed_document: ParsedDocument,
        transient_docling_document: object | None,
        supersede_previous: bool,
    ) -> DocumentChunkJob:
        job.status = DocumentChunkJobStatus.RUNNING.value
        job.attempt_count += 1
        job.started_at = utc_now()
        job.updated_at = utc_now()
        self.session.add(job)
        self.session.commit()

        logger.info(
            "Chunking started: job_id=%s parsed_document_id=%s",
            job.id,
            parsed_document.id,
        )

        try:
            if transient_docling_document is None:
                raise MissingDoclingDocumentError(
                    "Parser did not provide a memory document object for native chunking"
                )

            chunks = self.chunker.chunk(transient_docling_document)
            for index, chunk in enumerate(chunks):
                self._save_chunk(
                    job=job,
                    parsed_document=parsed_document,
                    sequence_index=index,
                    chunk=chunk,
                )

            job.status = DocumentChunkJobStatus.SUCCEEDED.value
            job.chunk_count = len(chunks)
            job.error_code = None
            job.error_message = None
            if supersede_previous:
                self._supersede_previous_jobs(parsed_document_id=parsed_document.id, keep_job=job)
            logger.info(
                "Chunking succeeded: job_id=%s chunks=%d",
                job.id,
                len(chunks),
            )
        except MissingDoclingDocumentError as exc:
            job.status = DocumentChunkJobStatus.FAILED.value
            job.error_code = "missing_docling_document"
            job.error_message = str(exc)
            logger.error(
                "Chunking failed: job_id=%s reason=missing_docling_document error=%s",
                job.id,
                exc,
                exc_info=True,
            )
        except Exception as exc:
            job.status = DocumentChunkJobStatus.FAILED.value
            job.error_code = "chunking_failed"
            job.error_message = str(exc)
            logger.error(
                "Chunking failed: job_id=%s reason=chunking_failed error=%s",
                job.id,
                exc,
                exc_info=True,
            )
        finally:
            job.finished_at = utc_now()
            job.updated_at = utc_now()
            self.session.add(job)
            self.session.commit()
            self.session.refresh(job)

        return job

    def _save_chunk(
        self,
        *,
        job: DocumentChunkJob,
        parsed_document: ParsedDocument,
        sequence_index: int,
        chunk: object,
    ) -> None:
        text = str(getattr(chunk, "text", ""))
        contextualized_text = str(getattr(chunk, "contextualized_text", text))
        stored = self.artifact_storage.save_texts(
            owner_user_id=job.owner_user_id,
            parsed_document_id=parsed_document.id,
            chunk_job_id=job.id,
            sequence_index=sequence_index,
            text=text,
            contextualized_text=contextualized_text,
            inline_text_max_bytes=self.config.inline_text_max_bytes,
        )
        self.session.add(
            DocumentChunk(
                chunk_job_id=job.id,
                parsed_document_id=parsed_document.id,
                owner_user_id=job.owner_user_id,
                sequence_index=sequence_index,
                text=stored.text,
                text_storage_key=stored.text_storage_key,
                contextualized_text=stored.contextualized_text,
                contextualized_text_storage_key=stored.contextualized_text_storage_key,
                token_count=getattr(chunk, "token_count", None),
                heading_path=getattr(chunk, "heading_path", None),
                page_numbers=getattr(chunk, "page_numbers", None),
                chunk_type=getattr(chunk, "chunk_type", "text"),
                source_segment_indices=getattr(chunk, "source_segment_indices", None),
                metadata_json=getattr(chunk, "metadata_json", None)
                or getattr(chunk, "metadata", None),
            )
        )
        self.session.flush()

    def _get_owned_parsed_document(
        self,
        *,
        parsed_document_id: UUID,
        owner_user_id: UUID,
    ) -> ParsedDocument:
        parsed_document = self.session.exec(
            select(ParsedDocument).where(
                ParsedDocument.id == parsed_document_id,
                ParsedDocument.owner_user_id == owner_user_id,
            )
        ).first()
        if parsed_document is None:
            raise DocumentChunkNotFoundError("Parsed document not found")
        return parsed_document

    def _get_running_job(self, *, parsed_document_id: UUID) -> DocumentChunkJob | None:
        return self.session.exec(
            select(DocumentChunkJob).where(
                DocumentChunkJob.parsed_document_id == parsed_document_id,
                col(DocumentChunkJob.status).in_(
                    [
                        DocumentChunkJobStatus.QUEUED.value,
                        DocumentChunkJobStatus.RUNNING.value,
                    ]
                ),
            )
        ).first()

    def _parse_original_file(
        self,
        *,
        parsed_document: ParsedDocument,
        parser: object | None,
    ) -> object | None:
        uploaded_file = self.session.get(UploadedFile, parsed_document.uploaded_file_id)
        if uploaded_file is None or self.upload_storage is None and parser is None:
            raise DocumentChunkOriginalFileUnavailableError("Original uploaded file is unavailable")

        if parser is None:
            try:
                source_path = self.upload_storage.path_for(uploaded_file.storage_key)
            except UploadStorageError as exc:
                raise DocumentChunkOriginalFileUnavailableError(
                    "Original uploaded file is unavailable"
                ) from exc
            if not Path(source_path).is_file():
                raise DocumentChunkOriginalFileUnavailableError(
                    "Original uploaded file is unavailable"
                )
            return DeferredOriginalFileDocument(source_path=source_path)

        result = parser.parse(uploaded_file)
        return getattr(result, "transient_docling_document", result)

    def _supersede_previous_jobs(
        self,
        *,
        parsed_document_id: UUID,
        keep_job: DocumentChunkJob,
    ) -> None:
        jobs = self.session.exec(
            select(DocumentChunkJob).where(
                DocumentChunkJob.parsed_document_id == parsed_document_id,
                DocumentChunkJob.id != keep_job.id,
                DocumentChunkJob.status == DocumentChunkJobStatus.SUCCEEDED.value,
            )
        ).all()
        for job in jobs:
            job.status = DocumentChunkJobStatus.SUPERSEDED.value
            job.updated_at = utc_now()
            self.session.add(job)


class MissingDoclingDocumentError(DocumentChunkingError):
    pass


@dataclass(frozen=True)
class DeferredOriginalFileDocument:
    source_path: Path
