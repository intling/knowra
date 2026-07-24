"""流水线存取验证 API 路由 —— 端到端验证「向量 → 分块 → 文档」数据完整性。

提供 GET /api/parsed-documents/{parsed_document_id}/pipeline-verification 端点，
执行只读验证并返回结构化验证报告。
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.session import get_session
from app.schemas.pipeline_verification import PipelineVerificationResponse
from app.services.document_chunk_storage import ChunkArtifactStorage
from app.services.pipeline_verification import (
    PipelineVerificationError,
    PipelineVerificationService,
)
from app.services.users import CurrentUserUnavailableError, get_current_user

logger = get_logger(__name__)

router = APIRouter(tags=["pipeline-verification"])
SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


# ── GET /api/parsed-documents/{parsed_document_id}/pipeline-verification ──


@router.get(
    "/parsed-documents/{parsed_document_id}/pipeline-verification",
    response_model=PipelineVerificationResponse,
)
def read_pipeline_verification(
    parsed_document_id: UUID,
    session: SessionDep,
    settings: SettingsDep,
) -> PipelineVerificationResponse:
    """对指定已解析文档执行完整的只读存取验证。

    沿「向量 → 分块 → 文档」JOIN 链路还原全链路数据，
    执行 7 项完整性检查，返回结构化验证报告。

    - **404**: parsed_document 不存在、无成功的分块作业、无成功的向量化作业
    - **503**: 当前用户不可用
    """
    # 权限校验：确认当前用户可用
    try:
        current_user = get_current_user(session)
    except CurrentUserUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Current user is unavailable",
        ) from exc

    logger.info(
        "Pipeline verification requested",
        parsed_document_id=str(parsed_document_id),
        user_id=str(current_user.id),
    )

    chunk_storage = ChunkArtifactStorage(settings.document_chunk_artifact_storage_dir)
    service = PipelineVerificationService(
        session=session,
        chunk_storage=chunk_storage,
    )

    try:
        return service.verify(
            parsed_document_id=parsed_document_id,
            owner_user_id=current_user.id,
        )
    except PipelineVerificationError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc
