from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from sqlmodel import Session

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.session import get_session
from app.schemas.upload import UploadedFileRead
from app.services.document_parse_dispatcher import BackgroundTasksParseJobDispatcher
from app.services.document_parsing import (
    DocumentParseConflictError,
    DocumentParseModelLoadingError,
    DocumentParseNotFoundError,
    DocumentParseService,
    DocumentParseTooLargeError,
    DocumentParsingDisabledError,
)
from app.services.document_parser import UnsupportedDocumentFormatError
from app.services.uploads import (
    LocalFileStorage,
    UploadMetadataError,
    UploadService,
    UploadStorageError,
    UploadTooLargeError,
    UploadValidationError,
)
from app.services.users import CurrentUserUnavailableError, get_current_user

logger = get_logger(__name__)

router = APIRouter(prefix="/uploads", tags=["uploads"])
SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post("", response_model=UploadedFileRead, status_code=status.HTTP_201_CREATED)
def create_upload(
    session: SessionDep,
    settings: SettingsDep,
    background_tasks: BackgroundTasks,
    request: Request,
    file: Annotated[UploadFile, File()],
    force: bool = False,
) -> UploadedFileRead:
    """上传文件并自动触发解析流水线。

    参数
    ----
    force : bool, default=False
        - ``False``：幂等模式。若已存在相同内容的文件，直接返回已有记录 (HTTP 200)。
        - ``True``：强制替换模式。软删除旧记录并重新走完整管线 (HTTP 201)。
    """
    try:
        current_user = get_current_user(session)
    except CurrentUserUnavailableError as exc:
        logger.error("当前用户不可用，无法上传文件")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Current user is unavailable",
        ) from exc

    service = UploadService(
        session=session,
        storage=LocalFileStorage(settings.upload_storage_dir),
        max_upload_bytes=settings.max_upload_bytes,
        allowed_content_types=set(settings.allowed_upload_content_types),
    )

    try:
        record, is_new = service.create_upload(current_user=current_user, file=file, force=force)
    except UploadTooLargeError as exc:
        logger.warning(
            "上传文件超过大小限制",
            file_name=file.filename,
            content_type=file.content_type,
        )
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="File size exceeds max_upload_bytes",
        ) from exc
    except UploadValidationError as exc:
        logger.warning(
            "上传文件校验失败",
            file_name=file.filename,
            reason=str(exc),
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (UploadStorageError, UploadMetadataError) as exc:
        logger.error(
            "上传文件存储或元数据保存失败",
            file_name=file.filename,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store uploaded file",
        ) from exc

    # ── 仅对新上传触发解析流水线；幂等命中时已有完整管线结果 ──────────
    if is_new:
        _try_auto_parse(session, settings, background_tasks, request, current_user, record.id)

    # 幂等命中返回 200，新上传返回 201
    status_code_to_use = status.HTTP_201_CREATED if is_new else status.HTTP_200_OK
    return JSONResponse(
        content=UploadedFileRead.model_validate(record, from_attributes=True).model_dump(mode="json"),
        status_code=status_code_to_use,
    )


# ── 自动触发解析流水线 ─────────────────────────────────────────────────────────


def _try_auto_parse(
    session: Session,
    settings: Settings,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user,
    upload_id: str,
) -> None:
    """上传成功后自动触发 解析 → 分块 → 向量化 流水线。

    最佳实践：上传即处理，避免用户需要手动触发。
    自动解析失败不影响上传响应——文件已安全存储，后续仍可手动解析。
    """
    # 总开关未启用时不触发
    if not settings.document_parse_enabled:
        logger.debug("文档解析未启用，跳过自动解析", upload_id=upload_id)
        return

    service = DocumentParseService(
        session=session,
        upload_storage=LocalFileStorage(settings.upload_storage_dir),
        document_parse_enabled=settings.document_parse_enabled,
        max_parse_bytes=settings.document_parse_max_bytes,
        max_parse_pages=settings.document_parse_max_pages,
        allowed_content_types=set(settings.document_parse_allowed_content_types),
        allowed_extensions=set(settings.document_parse_allowed_extensions),
    )
    model_readiness = getattr(request.app.state, "document_model_readiness", None)

    # 1. 校验：格式、模型就绪等
    try:
        service.ensure_parse_request_allowed(
            current_user=current_user,
            upload_id=upload_id,
            model_readiness=model_readiness,
        )
    except DocumentParsingDisabledError:
        logger.debug("文档解析已禁用，跳过自动解析", upload_id=upload_id)
        return
    except UnsupportedDocumentFormatError:
        logger.info(
            "文件格式不在解析支持范围内，跳过自动解析",
            upload_id=upload_id,
        )
        return
    except DocumentParseTooLargeError:
        logger.warning("文件过大，跳过自动解析", upload_id=upload_id)
        return
    except DocumentParseModelLoadingError:
        logger.warning(
            "Docling 模型未就绪，跳过自动解析（可稍后手动触发）",
            upload_id=upload_id,
        )
        return
    except DocumentParseNotFoundError:
        logger.warning("上传文件记录未找到，无法自动解析", upload_id=upload_id)
        return

    # 2. 创建解析任务（状态：queued）
    try:
        parse_job = service.create_parse_job(current_user=current_user, upload_id=upload_id)
    except DocumentParseConflictError:
        logger.info("解析任务已存在，跳过重复创建", upload_id=upload_id)
        return

    # 3. 委托到 BackgroundTasks 异步执行（parse → chunk → embed）
    BackgroundTasksParseJobDispatcher(background_tasks).enqueue(parse_job.id)

    logger.info(
        "上传成功，已自动创建解析任务",
        upload_id=upload_id,
        parse_job_id=parse_job.id,
    )
