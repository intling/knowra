"""文档向量化服务 —— 管理向量化作业的创建、执行、持久化和失败处理。

与 ``DocumentChunkingService`` 采用相同的设计模式：
- ``run_initial_embedding()`` 在分块成功后自动触发首次向量化
- ``execute_queued_job()`` 对 API 层已创建的 QUEUED 作业执行向量化
- ``_run_job()`` 封装完整的向量化生命周期
- 支持 graceful shutdown 协作式关闭检查
"""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from uuid import UUID

from sqlmodel import Session, col, select

from app.core.logging import get_logger
from app.db.session import engine
from app.models.document_chunking import DocumentChunk, DocumentChunkJob
from app.models.document_embedding import (
    DocumentEmbedding,
    DocumentEmbeddingJob,
    DocumentEmbeddingJobStatus,
)
from app.models.document_parsing import ParsedDocument
from app.models.user import utc_now
from app.services.embedding_adapter import (
    EmbeddingAdapter,
    EmbeddingAPIError,
    EmbeddingError,
    EmbeddingInvalidResponseError,
)
from app.services.embedding_config import EmbeddingConfig

logger = get_logger(__name__)

SessionFactory = Callable[[], Generator[Session]]


class ProcessShutdownError(Exception):
    """进程正在关闭，当前向量化作业无法继续。"""

    pass


class DocumentEmbeddingService:
    """管理文档向量化作业的完整生命周期。

    构造函数接收与 ``DocumentChunkingService`` 对齐的参数：
    - ``session``: 数据库会话
    - ``adapter``: 云端 embedding API 适配器
    - ``config``: embedding 配置
    - ``shutdown_state``: 进程关闭状态对象（可选）
    """

    def __init__(
        self,
        *,
        session: Session,
        adapter: EmbeddingAdapter,
        config: EmbeddingConfig,
        shutdown_state: object | None = None,
    ) -> None:
        self.session = session
        self.adapter = adapter
        self.config = config
        self.shutdown_state = shutdown_state

    # ── public API ──────────────────────────────────────────────────

    def run_initial_embedding(
        self,
        *,
        chunk_job: DocumentChunkJob,
        parsed_document: ParsedDocument,
    ) -> DocumentEmbeddingJob:
        """分块成功后自动触发首次向量化。

        创建向量化作业（状态 ``running``），加载 chunks 文本，调用适配器
        生成向量并持久化。首次向量化无旧结果需取代，以 ``supersede_previous=False``
        模式运行。
        """
        job = self._create_job(
            chunk_job=chunk_job,
            parsed_document=parsed_document,
        )
        chunks = self._load_chunks_for_job(chunk_job.id)
        return self._run_job(
            job=job,
            chunks=chunks,
            supersede_previous=False,
        )

    def execute_queued_job(
        self,
        *,
        job: DocumentEmbeddingJob,
        chunks: list[DocumentChunk],
    ) -> DocumentEmbeddingJob:
        """对 API 层已创建的 QUEUED 作业执行向量化，始终 supersede 旧结果。

        不调用 ``_create_job()`` —— 直接使用传入的 *job* 参数。
        """
        return self._run_job(
            job=job,
            chunks=chunks,
            supersede_previous=True,
        )

    # ── internal: job lifecycle ─────────────────────────────────────

    def _create_job(
        self,
        *,
        chunk_job: DocumentChunkJob,
        parsed_document: ParsedDocument,
    ) -> DocumentEmbeddingJob:
        """创建 ``queued`` 状态的 ``DocumentEmbeddingJob``，保存 ``config_json`` 快照。"""
        now = utc_now()
        job = DocumentEmbeddingJob(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status=DocumentEmbeddingJobStatus.QUEUED.value,
            model=self.config.model,
            dimensions=self.config.dimensions,
            config_json=self.config.snapshot(),
            created_at=now,
            updated_at=now,
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        logger.info(
            "Embedding job created",
            job_id=str(job.id),
            chunk_job_id=str(chunk_job.id),
        )
        return job

    def _run_job(
        self,
        *,
        job: DocumentEmbeddingJob,
        chunks: list[DocumentChunk],
        supersede_previous: bool,
    ) -> DocumentEmbeddingJob:
        """执行完整向量化流程：running → 文本收集 → API 调用 → 持久化 → 取代旧结果。

        所有失败路径均在方法内部捕获，将作业标记为 ``failed`` 而不抛出异常。
        """
        job.status = DocumentEmbeddingJobStatus.RUNNING.value
        job.attempt_count += 1
        job.started_at = utc_now()
        job.updated_at = utc_now()
        self.session.add(job)
        self.session.commit()

        logger.info(
            "Embedding started",
            job_id=str(job.id),
            chunk_job_id=str(job.chunk_job_id),
            chunk_count=len(chunks),
        )

        try:
            self._ensure_not_shutting_down()

            # 收集向量化文本：优先使用 contextualized_text，fallback 到 text
            texts = [chunk.contextualized_text or chunk.text or "" for chunk in chunks]

            # 调用云端 API
            results = self.adapter.embed(texts)

            # 写入前再次检查 shutdown 状态
            self._ensure_not_shutting_down()

            # 持久化向量结果
            self._save_embeddings(
                job=job,
                chunks=chunks,
                results=sorted(results, key=lambda r: r.index),
            )

            job.status = DocumentEmbeddingJobStatus.SUCCEEDED.value
            job.embedding_count = len(results)
            job.error_code = None
            job.error_message = None

            if supersede_previous:
                self._supersede_previous_jobs(
                    chunk_job_id=job.chunk_job_id,
                    keep_job=job,
                )

            logger.info(
                "Embedding succeeded",
                job_id=str(job.id),
                embedding_count=len(results),
            )
        except EmbeddingInvalidResponseError as exc:
            job.status = DocumentEmbeddingJobStatus.FAILED.value
            job.error_code = "invalid_response"
            job.error_message = str(exc)
            logger.error(
                "Embedding failed",
                job_id=str(job.id),
                reason="invalid_response",
                error=str(exc),
                exc_info=True,
            )
        except EmbeddingAPIError as exc:
            job.status = DocumentEmbeddingJobStatus.FAILED.value
            job.error_code = "api_error"
            job.error_message = str(exc)
            logger.error(
                "Embedding failed",
                job_id=str(job.id),
                reason="api_error",
                error=str(exc),
                exc_info=True,
            )
        except EmbeddingError as exc:
            job.status = DocumentEmbeddingJobStatus.FAILED.value
            job.error_code = "api_error"
            job.error_message = str(exc)
            logger.error(
                "Embedding failed",
                job_id=str(job.id),
                reason="api_error",
                error=str(exc),
                exc_info=True,
            )
        except ProcessShutdownError as exc:
            job.status = DocumentEmbeddingJobStatus.FAILED.value
            job.error_code = "process_shutdown"
            job.error_message = str(exc)
            logger.warning(
                "Embedding stopped for process shutdown",
                job_id=str(job.id),
                reason="process_shutdown",
                error=str(exc),
            )
        except Exception as exc:
            job.status = DocumentEmbeddingJobStatus.FAILED.value
            job.error_code = "api_error"
            job.error_message = str(exc)
            logger.error(
                "Embedding failed",
                job_id=str(job.id),
                reason="api_error",
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

    # ── internal: helpers ────────────────────────────────────────────

    def _load_chunks_for_job(self, chunk_job_id: UUID) -> list[DocumentChunk]:
        """加载分块作业的所有 chunks，按 ``sequence_index`` 排序。"""
        return list(
            self.session.exec(
                select(DocumentChunk)
                .where(DocumentChunk.chunk_job_id == chunk_job_id)
                .order_by(DocumentChunk.sequence_index)
            ).all()
        )

    def _save_embeddings(
        self,
        *,
        job: DocumentEmbeddingJob,
        chunks: list[DocumentChunk],
        results: list,
    ) -> None:
        """批量为每个 chunk 创建 ``DocumentEmbedding`` 记录。

        *results* 是按 ``index`` 排序后的 ``EmbeddingResult`` 列表，
        其顺序与 *chunks* 一一对应。
        """
        for _i, (chunk, result) in enumerate(zip(chunks, results, strict=True)):
            self.session.add(
                DocumentEmbedding(
                    embedding_job_id=job.id,
                    chunk_id=chunk.id,
                    parsed_document_id=job.parsed_document_id,
                    owner_user_id=job.owner_user_id,
                    sequence_index=chunk.sequence_index,
                    model=job.model,
                    dimensions=job.dimensions,
                    embedding_json=result.embedding,
                    embedding_vector=result.embedding,
                    token_count=result.token_count,
                )
            )
        self.session.flush()
        logger.debug(
            "Embedding records persisted",
            job_id=str(job.id),
            count=len(results),
            dual_write=True,
        )

    def _supersede_previous_jobs(
        self,
        *,
        chunk_job_id: UUID,
        keep_job: DocumentEmbeddingJob,
    ) -> None:
        """将同一 ``chunk_job_id`` 下的旧 ``succeeded`` 作业标记为 ``superseded``。"""
        jobs = self.session.exec(
            select(DocumentEmbeddingJob).where(
                DocumentEmbeddingJob.chunk_job_id == chunk_job_id,
                DocumentEmbeddingJob.id != keep_job.id,
                DocumentEmbeddingJob.status == DocumentEmbeddingJobStatus.SUCCEEDED.value,
            )
        ).all()
        for old_job in jobs:
            old_job.status = DocumentEmbeddingJobStatus.SUPERSEDED.value
            old_job.updated_at = utc_now()
            self.session.add(old_job)
        if jobs:
            logger.info(
                "Superseded previous embedding jobs",
                chunk_job_id=str(chunk_job_id),
                superseded_count=len(jobs),
            )

    def _ensure_not_shutting_down(self) -> None:
        """检查进程关闭状态，发现关闭时抛出 ``ProcessShutdownError``。"""
        if getattr(self.shutdown_state, "is_shutting_down", False):
            raise ProcessShutdownError("Process shutdown before embedding job could finish")


# ── 模块级辅助函数 ──────────────────────────────────────────────────


def _is_shutting_down(shutdown_state: object | None) -> bool:
    """检查进程是否正在关闭。"""
    return bool(getattr(shutdown_state, "is_shutting_down", False))


def _mark_embedding_job_process_shutdown(*, session: Session, job: DocumentEmbeddingJob) -> None:
    """将向量化作业标记为 process_shutdown 失败。"""
    job.status = DocumentEmbeddingJobStatus.FAILED.value
    job.error_code = "process_shutdown"
    job.error_message = "Process shutdown before embedding job could finish"
    job.finished_at = utc_now()
    job.updated_at = utc_now()
    session.add(job)
    session.commit()


def _coerce_uuid(value: UUID | str) -> UUID:
    """将字符串或 UUID 统一转为 UUID。"""
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


@contextmanager
def default_session_factory() -> Generator[Session]:
    """默认 session 工厂，供后台执行函数使用。"""
    with Session(engine) as session:
        yield session


def mark_incomplete_embedding_jobs_failed_for_shutdown(*, session: Session, reason: str) -> int:
    """将 ``queued`` 和 ``running`` 的向量化作业标记为 ``failed``（shutdown 收尾）。

    Returns:
        被标记的作业数量。
    """
    jobs = session.exec(
        select(DocumentEmbeddingJob).where(
            col(DocumentEmbeddingJob.status).in_(
                [
                    DocumentEmbeddingJobStatus.QUEUED.value,
                    DocumentEmbeddingJobStatus.RUNNING.value,
                ]
            )
        )
    ).all()
    for job in jobs:
        job.status = DocumentEmbeddingJobStatus.FAILED.value
        job.error_code = "process_shutdown"
        job.error_message = f"Process shutdown before embedding job could finish: {reason}"
        job.finished_at = utc_now()
        job.updated_at = utc_now()
        session.add(job)
    session.commit()
    logger.info(
        "Marked incomplete embedding jobs as failed for shutdown",
        reason=reason,
        count=len(jobs),
    )
    return len(jobs)
