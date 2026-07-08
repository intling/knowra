from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from fastapi import BackgroundTasks
from sqlmodel import Session, col, select

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import engine
from app.models.document_chunking import DocumentChunk, DocumentChunkJob, DocumentChunkJobStatus
from app.models.document_parsing import ParsedDocument
from app.models.uploaded_file import UploadedFile
from app.models.user import utc_now
from app.services.document_chunk_storage import ChunkArtifactStorage
from app.services.document_chunker import (
    DoclingChunkerAdapter,
    DocumentChunkingConfig,
    DocumentChunkingError,
)
from app.services.document_parser import (
    DoclingParserAdapter,
    DocumentFormatPolicy,
    ParsedDocumentResult,
)
from app.services.uploads import LocalFileStorage

logger = get_logger(__name__)

SessionFactory = Callable[[], Generator[Session]]


class DocumentChunkNotFoundError(Exception):
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
        model_readiness: object | None = None,
        shutdown_state: object | None = None,
    ) -> None:
        self.session = session
        self.chunker = chunker
        self.artifact_storage = artifact_storage
        self.config = config
        self.model_readiness = model_readiness
        self.shutdown_state = shutdown_state

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

    def execute_queued_job(
        self,
        *,
        job: DocumentChunkJob,
        parsed_document: ParsedDocument,
        transient_docling_document: object | None,
    ) -> DocumentChunkJob:
        """对 API 层已创建的 QUEUED 作业执行分块，始终 supersede 旧结果。"""
        return self._run_job(
            job=job,
            parsed_document=parsed_document,
            transient_docling_document=transient_docling_document,
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
            "Chunking started",
            job_id=str(job.id),
            parsed_document_id=str(parsed_document.id),
        )

        try:
            self._ensure_not_shutting_down()
            self._ensure_tokenizer_ready()
            if transient_docling_document is None:
                raise MissingDoclingDocumentError(
                    "Parser did not provide a memory document object for native chunking"
                )

            chunks = self.chunker.chunk(transient_docling_document)
            self._ensure_not_shutting_down()
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
            logger.info("Chunking succeeded", job_id=str(job.id), chunks=len(chunks))
        except MissingDoclingDocumentError as exc:
            job.status = DocumentChunkJobStatus.FAILED.value
            job.error_code = "missing_docling_document"
            job.error_message = str(exc)
            logger.error(
                "Chunking failed",
                job_id=str(job.id),
                reason="missing_docling_document",
                error=str(exc),
                exc_info=True,
            )
        except DocumentModelUnavailableError as exc:
            job.status = DocumentChunkJobStatus.FAILED.value
            job.error_code = "model_unavailable"
            job.error_message = str(exc)
            logger.error(
                "Chunking failed",
                job_id=str(job.id),
                reason="model_unavailable",
                error=str(exc),
                exc_info=True,
            )
        except ProcessShutdownError as exc:
            job.status = DocumentChunkJobStatus.FAILED.value
            job.error_code = "process_shutdown"
            job.error_message = str(exc)
            logger.warning(
                "Chunking stopped for process shutdown",
                job_id=str(job.id),
                reason="process_shutdown",
                error=str(exc),
            )
        except Exception as exc:
            job.status = DocumentChunkJobStatus.FAILED.value
            job.error_code = "chunking_failed"
            job.error_message = str(exc)
            logger.error(
                "Chunking failed",
                job_id=str(job.id),
                reason="chunking_failed",
                error=str(exc),
                exc_info=True,
            )
        finally:
            job.finished_at = utc_now()
            job.updated_at = utc_now()
            self.session.add(job)
            self.session.commit()
            self.session.refresh(job)

        return job

    def _ensure_tokenizer_ready(self) -> None:
        tokenizer = getattr(self.model_readiness, "tokenizer", None)
        if tokenizer is None or getattr(tokenizer, "status", "ready") == "ready":
            return
        if getattr(tokenizer, "status", "ready") == "skipped":
            return
        if getattr(tokenizer, "status", "ready") == "loading":
            raise DocumentModelUnavailableError("Tokenizer models are still loading")
        missing = ", ".join(getattr(tokenizer, "missing_models", []) or [])
        detail = (
            f"Tokenizer models are unavailable: {missing}"
            if missing
            else "Tokenizer models are unavailable"
        )
        raise DocumentModelUnavailableError(detail)

    def _ensure_not_shutting_down(self) -> None:
        if getattr(self.shutdown_state, "is_shutting_down", False):
            raise ProcessShutdownError("Process shutdown before chunk job could finish")

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


class DocumentModelUnavailableError(DocumentChunkingError):
    pass


class ProcessShutdownError(DocumentChunkingError):
    pass


class RechunkDispatcher:
    """将 rechunk 作业入队到 FastAPI BackgroundTasks 的轻量调度器。

    结构复制 ``BackgroundTasksParseJobDispatcher``，为 rechunk 提供与 parse
    一致的后台执行范式。
    """

    def __init__(self, background_tasks: BackgroundTasks) -> None:
        self.background_tasks = background_tasks

    def enqueue(self, job_id: UUID) -> None:
        self.background_tasks.add_task(run_rechunk_job, job_id)


def run_rechunk_job(
    job_id: UUID,
    *,
    session_factory: SessionFactory | None = None,
    parser: object | None = None,
    upload_storage_root: str | Path | None = None,
    chunking_service: object | None = None,
    model_readiness: object | None = None,
    shutdown_state: object | None = None,
) -> None:
    """后台执行 rechunk 作业。

    从 DB 加载 QUEUED 分块作业，重新解析原始文件获得内存 ``DoclingDocument``，
    再委托 ``DocumentChunkingService.execute_queued_job()`` 执行分块并持久化。

    所有参数均可选注入，便于测试；未注入时使用生产默认值。
    """
    settings = get_settings()
    session_context = session_factory or default_session_factory

    with session_context() as session:
        job = session.get(DocumentChunkJob, _coerce_uuid(job_id))
        if job is None or job.status != DocumentChunkJobStatus.QUEUED.value:
            return

        logger.info("重新分块开始", job_id=str(job.id))

        try:
            if _is_shutting_down(shutdown_state):
                _mark_chunk_job_process_shutdown(session=session, job=job)
                return

            parsed_document = session.get(ParsedDocument, job.parsed_document_id)
            if parsed_document is None:
                raise ValueError("Parsed document not found")

            uploaded_file = session.get(UploadedFile, parsed_document.uploaded_file_id)
            if uploaded_file is None:
                raise ValueError("Uploaded file not found")

            upload_storage = LocalFileStorage(upload_storage_root or settings.upload_storage_dir)
            source_path = upload_storage.path_for(uploaded_file.storage_key)
            if not Path(source_path).is_file():
                raise FileNotFoundError(f"Original uploaded file not found: {source_path}")

            active_parser = parser or DoclingParserAdapter(
                ocr_enabled=settings.document_parse_ocr_enabled,
                max_pages=settings.document_parse_max_pages,
                docling_artifact_dir=_get_docling_artifact_dir(settings, model_readiness),
                converter=_get_docling_converter(model_readiness),
            )
            document_format = DocumentFormatPolicy(
                allowed_content_types=set(settings.document_parse_allowed_content_types),
                allowed_extensions=set(settings.document_parse_allowed_extensions),
            ).validate(
                source_path,
                original_filename=uploaded_file.original_filename,
                content_type=uploaded_file.content_type,
            )

            parse_result = _normalize_parse_result(
                active_parser.parse(source_path, document_format=document_format)
            )

            if _is_shutting_down(shutdown_state):
                _mark_chunk_job_process_shutdown(session=session, job=job)
                return

            service = chunking_service or _make_chunking_service(
                session=session,
                settings=settings,
                model_readiness=model_readiness,
            )
            service.execute_queued_job(
                job=job,
                parsed_document=parsed_document,
                transient_docling_document=parse_result.transient_docling_document,
            )
        except Exception as exc:
            # _run_job 内部已处理分块阶段的错误；这里只处理解析阶段的错误。
            session.refresh(job)
            if job.status in (
                DocumentChunkJobStatus.FAILED.value,
                DocumentChunkJobStatus.SUCCEEDED.value,
            ):
                return

            job.status = DocumentChunkJobStatus.FAILED.value
            job.error_code = "chunking_failed"
            job.error_message = str(exc)
            job.finished_at = utc_now()
            job.updated_at = utc_now()
            session.add(job)
            session.commit()
            logger.error(
                "重新分块失败",
                job_id=str(job.id),
                error=str(exc),
                exc_info=True,
            )


# ── 模块内部辅助函数 ──────────────────────────────────────────────


def _make_chunking_service(
    *,
    session: Session,
    settings,
    model_readiness: object | None = None,
) -> DocumentChunkingService:
    """构建 ``DocumentChunkingService``，供 ``run_rechunk_job`` 内部使用。"""
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
        model_readiness=model_readiness,
    )


def _get_docling_artifact_dir(settings, model_readiness: object | None) -> str:
    """从 model_readiness 或 settings 解析 Docling artifact 目录。"""
    docling = getattr(model_readiness, "docling", None)
    artifact_dir = getattr(docling, "artifact_dir", None)
    if artifact_dir:
        return str(artifact_dir)
    return settings.document_model_docling_artifact_dir


def _get_docling_converter(model_readiness: object | None) -> object | None:
    """从 model_readiness 提取预初始化的 Docling converter（如有）。"""
    docling = getattr(model_readiness, "docling", None)
    return getattr(docling, "resource", None)


def _is_shutting_down(shutdown_state: object | None) -> bool:
    """检查进程是否正在关闭。"""
    return bool(getattr(shutdown_state, "is_shutting_down", False))


def _mark_chunk_job_process_shutdown(*, session: Session, job: DocumentChunkJob) -> None:
    """将分块作业标记为 process_shutdown 失败。"""
    job.status = DocumentChunkJobStatus.FAILED.value
    job.error_code = "process_shutdown"
    job.error_message = "Process shutdown before rechunk job could finish"
    job.finished_at = utc_now()
    job.updated_at = utc_now()
    session.add(job)
    session.commit()


def _coerce_uuid(value: UUID | str) -> UUID:
    """将字符串或 UUID 统一转为 UUID。"""
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def _normalize_parse_result(result: ParsedDocumentResult | object) -> ParsedDocumentResult:
    """将解析结果统一为 ``ParsedDocumentResult``。

    某些解析适配器直接返回 ``ParsedDocumentResult``，有些返回
    ``ParsedDocumentPayload``，后者需要包装。
    """
    if isinstance(result, ParsedDocumentResult):
        return result
    return ParsedDocumentResult(
        persistent_payload=result,
        transient_docling_document=getattr(result, "transient_docling_document", None),
    )


@contextmanager
def default_session_factory() -> Generator[Session]:
    """默认 session 工厂，供 ``run_rechunk_job`` 使用。"""
    with Session(engine) as session:
        yield session


def mark_incomplete_chunk_jobs_failed_for_shutdown(*, session: Session, reason: str) -> int:
    jobs = session.exec(
        select(DocumentChunkJob).where(
            col(DocumentChunkJob.status).in_(
                [
                    DocumentChunkJobStatus.QUEUED.value,
                    DocumentChunkJobStatus.RUNNING.value,
                ]
            )
        )
    ).all()
    for job in jobs:
        job.status = DocumentChunkJobStatus.FAILED.value
        job.error_code = "process_shutdown"
        job.error_message = f"Process shutdown before chunk job could finish: {reason}"
        job.finished_at = utc_now()
        job.updated_at = utc_now()
        session.add(job)
    session.commit()
    return len(jobs)
