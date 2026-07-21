"""向量化 API 路由 —— 向量化作业查询、向量结果查询和重新向量化。

所有端点均校验当前用户权限，遵循与 document_chunking 路由相同的模式。
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.session import get_session
from app.models.document_chunking import DocumentChunk, DocumentChunkJob
from app.models.document_embedding import (
    DocumentEmbedding,
    DocumentEmbeddingJob,
    DocumentEmbeddingJobStatus,
)
from app.models.user import utc_now
from app.schemas.document_embedding import (
    EmbeddingConflictResponse,
    EmbeddingJobResponse,
    EmbeddingPageResponse,
    EmbeddingResponse,
    ReEmbedRequest,
)
from app.services.document_embedding import (
    DocumentEmbeddingService,
    ProcessShutdownError,
    SessionFactory,
    _coerce_uuid,
    _is_shutting_down,
    _mark_embedding_job_process_shutdown,
    default_session_factory,
)
from app.services.embedding_adapter import EmbeddingAdapter
from app.services.embedding_config import EmbeddingConfig
from app.services.users import CurrentUserUnavailableError, get_current_user

logger = get_logger(__name__)

router = APIRouter(tags=["document-embedding"])
SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


# ── GET /api/document-embedding-jobs/{job_id} ──────────────────────────


@router.get(
    "/document-embedding-jobs/{job_id}",
    response_model=EmbeddingJobResponse,
)
def read_document_embedding_job(job_id: UUID, session: SessionDep) -> EmbeddingJobResponse:
    """查询向量化作业状态，校验当前用户权限。"""
    current_user = require_current_user(session)
    logger.info("Querying embedding job", job_id=str(job_id))
    job = session.exec(
        select(DocumentEmbeddingJob).where(
            DocumentEmbeddingJob.id == job_id,
            DocumentEmbeddingJob.owner_user_id == current_user.id,
        )
    ).first()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Embedding job not found")
    return EmbeddingJobResponse.model_validate(job, from_attributes=True)


# ── GET /api/document-chunk-jobs/{chunk_job_id}/embedding-job ────────────


@router.get(
    "/document-chunk-jobs/{chunk_job_id}/embedding-job",
    response_model=EmbeddingJobResponse,
)
def read_chunk_job_latest_embedding_job(
    chunk_job_id: UUID,
    session: SessionDep,
) -> EmbeddingJobResponse:
    """查询分块作业最新的向量化作业（不限状态），用于前端展示向量化进度。"""
    current_user = require_current_user(session)
    logger.info("Querying latest embedding job for chunk job", chunk_job_id=str(chunk_job_id))
    chunk_job = get_owned_chunk_job(
        session=session,
        chunk_job_id=chunk_job_id,
        owner_user_id=current_user.id,
    )
    job = session.exec(
        select(DocumentEmbeddingJob)
        .where(DocumentEmbeddingJob.chunk_job_id == chunk_job.id)
        .order_by(col(DocumentEmbeddingJob.created_at).desc())
    ).first()
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No embedding job found for this chunk job",
        )
    return EmbeddingJobResponse.model_validate(job, from_attributes=True)


# ── GET /api/document-chunk-jobs/{chunk_job_id}/embeddings ──────────────


@router.get(
    "/document-chunk-jobs/{chunk_job_id}/embeddings",
    response_model=EmbeddingPageResponse,
)
def read_chunk_job_embeddings(
    chunk_job_id: UUID,
    session: SessionDep,
    offset: int = 0,
    limit: int = 50,
) -> EmbeddingPageResponse:
    """分页查询分块作业的最新活跃向量结果，按 ``sequence_index`` 排序。"""
    current_user = require_current_user(session)
    logger.info("Querying chunk job embeddings", chunk_job_id=str(chunk_job_id))
    chunk_job = get_owned_chunk_job(
        session=session,
        chunk_job_id=chunk_job_id,
        owner_user_id=current_user.id,
    )
    active_job = get_latest_active_embedding_job(
        session=session,
        chunk_job_id=chunk_job.id,
    )
    normalized_offset = max(0, offset)
    bounded_limit = max(1, min(limit, 200))

    if active_job is None:
        return EmbeddingPageResponse(
            items=[],
            total=0,
            offset=normalized_offset,
            limit=bounded_limit,
        )

    total = session.exec(
        select(func.count(DocumentEmbedding.id)).where(
            DocumentEmbedding.embedding_job_id == active_job.id,
        )
    ).one()

    embeddings = session.exec(
        select(DocumentEmbedding)
        .where(DocumentEmbedding.embedding_job_id == active_job.id)
        .order_by(DocumentEmbedding.sequence_index)
        .offset(normalized_offset)
        .limit(bounded_limit)
    ).all()

    return EmbeddingPageResponse(
        items=[_to_embedding_response(emb) for emb in embeddings],
        total=total,
        offset=normalized_offset,
        limit=bounded_limit,
    )


# ── GET /api/document-chunks/{chunk_id}/embedding ──────────────────────


@router.get(
    "/document-chunks/{chunk_id}/embedding",
    response_model=EmbeddingResponse,
)
def read_chunk_embedding(chunk_id: UUID, session: SessionDep) -> EmbeddingResponse:
    """查询单个 chunk 的向量详情。"""
    current_user = require_current_user(session)
    logger.info("Querying chunk embedding", chunk_id=str(chunk_id))
    chunk = session.exec(
        select(DocumentChunk).where(
            DocumentChunk.id == chunk_id,
            DocumentChunk.owner_user_id == current_user.id,
        )
    ).first()
    if chunk is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chunk not found")

    # 获取最新活跃向量化作业中该 chunk 的向量结果
    active_job = get_latest_active_embedding_job(
        session=session,
        chunk_job_id=chunk.chunk_job_id,
    )
    if active_job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active embedding found for this chunk",
        )

    embedding = session.exec(
        select(DocumentEmbedding).where(
            DocumentEmbedding.embedding_job_id == active_job.id,
            DocumentEmbedding.chunk_id == chunk_id,
        )
    ).first()
    if embedding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Embedding not found for this chunk",
        )

    return _to_embedding_response(embedding)


# ── POST /api/document-chunk-jobs/{chunk_job_id}/re-embed ──────────────


@router.post(
    "/document-chunk-jobs/{chunk_job_id}/re-embed",
    response_model=EmbeddingJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def reembed_chunk_job(
    chunk_job_id: UUID,
    http_request: Request,
    session: SessionDep,
    settings: SettingsDep,
    background_tasks: BackgroundTasks,
    request: ReEmbedRequest | None = None,
) -> EmbeddingJobResponse | JSONResponse:
    """创建重新向量化作业（202）。

    校验分块作业存在且属于当前用户，校验无运行中作业（409），
    校验 shutdown 状态（503），通过 ``BackgroundTasks`` 调度后台执行。
    """
    # shutdown 检查
    if getattr(
        getattr(http_request.app.state, "application_shutdown_state", None),
        "is_shutting_down",
        False,
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service is shutting down",
        )

    current_user = require_current_user(session)
    logger.info(
        "Re-embed request received",
        chunk_job_id=str(chunk_job_id),
    )

    chunk_job = get_owned_chunk_job(
        session=session,
        chunk_job_id=chunk_job_id,
        owner_user_id=current_user.id,
    )

    # 409: 已有运行中作业
    running_job = get_running_embedding_job(
        session=session,
        chunk_job_id=chunk_job.id,
    )
    if running_job is not None:
        payload = EmbeddingConflictResponse(
            detail="Embedding job already running",
            job=EmbeddingJobResponse.model_validate(running_job, from_attributes=True),
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=jsonable_encoder(payload),
        )

    config = _make_embedding_config(settings=settings, request=request)
    job = _create_queued_embedding_job(
        session=session,
        chunk_job=chunk_job,
        config=config,
    )
    ReembedDispatcher(background_tasks).enqueue(job.id)
    return EmbeddingJobResponse.model_validate(job, from_attributes=True)


# ── Background dispatcher & executor ───────────────────────────────────


class ReembedDispatcher:
    """将重新向量化作业入队到 FastAPI BackgroundTasks 的轻量调度器。

    结构复制 ``RechunkDispatcher``，为 re-embed 提供一致的后台执行范式。
    """

    def __init__(self, background_tasks: BackgroundTasks) -> None:
        self.background_tasks = background_tasks

    def enqueue(self, job_id: UUID) -> None:
        self.background_tasks.add_task(run_reembed_job, job_id)


def run_reembed_job(
    job_id: UUID,
    *,
    session_factory: SessionFactory | None = None,
    embedding_adapter: object | None = None,
    shutdown_state: object | None = None,
) -> None:
    """后台执行重新向量化作业。

    从 DB 加载 QUEUED 向量化作业，读取已有 chunks 文本，
    委托 ``DocumentEmbeddingService.execute_queued_job()`` 执行向量化并持久化。

    所有参数均可选注入，便于测试；未注入时使用生产默认值。
    """
    session_context = session_factory or default_session_factory

    with session_context() as session:
        job = session.get(DocumentEmbeddingJob, _coerce_uuid(job_id))
        if job is None or job.status != DocumentEmbeddingJobStatus.QUEUED.value:
            return

        logger.info(
            "Re-embed job started",
            job_id=str(job.id),
            chunk_job_id=str(job.chunk_job_id),
        )

        try:
            if _is_shutting_down(shutdown_state):
                _mark_embedding_job_process_shutdown(session=session, job=job)
                return

            # 加载已有 chunks
            chunks = list(
                session.exec(
                    select(DocumentChunk)
                    .where(DocumentChunk.chunk_job_id == job.chunk_job_id)
                    .order_by(DocumentChunk.sequence_index)
                ).all()
            )
            if not chunks:
                raise ValueError("No chunks found for the chunk job")

            config = EmbeddingConfig.from_settings()
            adapter = embedding_adapter or EmbeddingAdapter(config=config)

            service = DocumentEmbeddingService(
                session=session,
                adapter=adapter,
                config=config,
                shutdown_state=shutdown_state,
            )
            service.execute_queued_job(job=job, chunks=chunks)

        except ProcessShutdownError as exc:
            # 向量化已由服务层标记为 process_shutdown
            logger.warning(
                "Re-embed stopped for process shutdown",
                job_id=str(job.id),
                error=str(exc),
            )
        except Exception as exc:
            # execute_queued_job 内部已将作业标记为 failed
            session.refresh(job)
            if job.status != DocumentEmbeddingJobStatus.FAILED.value:
                job.status = DocumentEmbeddingJobStatus.FAILED.value
                job.error_code = "reembed_failed"
                job.error_message = str(exc)
                job.finished_at = utc_now()
                job.updated_at = utc_now()
                session.add(job)
                session.commit()
            logger.error(
                "Re-embed job failed",
                job_id=str(job.id),
                error=str(exc),
                exc_info=True,
            )


# ── Helper functions ───────────────────────────────────────────────────


def require_current_user(session: Session):
    try:
        return get_current_user(session)
    except CurrentUserUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Current user is unavailable",
        ) from exc


def get_owned_chunk_job(
    *,
    session: Session,
    chunk_job_id: UUID,
    owner_user_id: UUID,
) -> DocumentChunkJob:
    """获取属于当前用户的分块作业，不存在时返回 404。"""
    chunk_job = session.exec(
        select(DocumentChunkJob).where(
            DocumentChunkJob.id == chunk_job_id,
            DocumentChunkJob.owner_user_id == owner_user_id,
        )
    ).first()
    if chunk_job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chunk job not found",
        )
    return chunk_job


def get_latest_active_embedding_job(
    *,
    session: Session,
    chunk_job_id: UUID,
) -> DocumentEmbeddingJob | None:
    """获取分块作业的最新非 superseded 成功向量化作业。"""
    return session.exec(
        select(DocumentEmbeddingJob)
        .where(
            DocumentEmbeddingJob.chunk_job_id == chunk_job_id,
            DocumentEmbeddingJob.status == DocumentEmbeddingJobStatus.SUCCEEDED.value,
        )
        .order_by(col(DocumentEmbeddingJob.created_at).desc())
    ).first()


def get_running_embedding_job(
    *,
    session: Session,
    chunk_job_id: UUID,
) -> DocumentEmbeddingJob | None:
    """查找分块作业下当前 queued 或 running 的向量化作业。"""
    return session.exec(
        select(DocumentEmbeddingJob).where(
            DocumentEmbeddingJob.chunk_job_id == chunk_job_id,
            col(DocumentEmbeddingJob.status).in_(
                [
                    DocumentEmbeddingJobStatus.QUEUED.value,
                    DocumentEmbeddingJobStatus.RUNNING.value,
                ]
            ),
        )
    ).first()


def _make_embedding_config(
    *,
    settings: Settings,
    request: ReEmbedRequest | None = None,
) -> EmbeddingConfig:
    """从应用配置和可选请求参数构建 ``EmbeddingConfig``。"""
    return EmbeddingConfig(
        api_base_url=settings.document_embedding_api_base_url,
        api_key=settings.document_embedding_api_key,
        model=request.model if request and request.model else settings.document_embedding_model,
        dimensions=(
            request.dimensions
            if request and request.dimensions
            else settings.document_embedding_dimensions
        ),
        encoding_format=settings.document_embedding_encoding_format,
        batch_size=settings.document_embedding_batch_size,
        max_retries=settings.document_embedding_max_retries,
        request_timeout=settings.document_embedding_request_timeout,
    )


def _create_queued_embedding_job(
    *,
    session: Session,
    chunk_job: DocumentChunkJob,
    config: EmbeddingConfig,
) -> DocumentEmbeddingJob:
    """创建 ``queued`` 状态的 ``DocumentEmbeddingJob``，保存 config_json 快照。"""
    now = utc_now()
    job = DocumentEmbeddingJob(
        chunk_job_id=chunk_job.id,
        parsed_document_id=chunk_job.parsed_document_id,
        owner_user_id=chunk_job.owner_user_id,
        status=DocumentEmbeddingJobStatus.QUEUED.value,
        model=config.model,
        dimensions=config.dimensions,
        config_json=config.snapshot(),
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    logger.info(
        "Embedding job created for re-embed",
        job_id=str(job.id),
        chunk_job_id=str(chunk_job.id),
    )
    return job


def _to_embedding_response(embedding: DocumentEmbedding) -> EmbeddingResponse:
    """将 ``DocumentEmbedding`` 模型转换为 ``EmbeddingResponse``。"""
    return EmbeddingResponse(
        id=embedding.id,
        chunk_id=embedding.chunk_id,
        embedding_job_id=embedding.embedding_job_id,
        sequence_index=embedding.sequence_index,
        model=embedding.model,
        dimensions=embedding.dimensions,
        embedding_json=embedding.embedding_json,
        token_count=embedding.token_count,
        created_at=embedding.created_at,
    )
