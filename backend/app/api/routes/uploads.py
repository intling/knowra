from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlmodel import Session

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.session import get_session
from app.schemas.upload import UploadedFileRead
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
    file: Annotated[UploadFile, File()],
) -> UploadedFileRead:
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
        record = service.create_upload(current_user=current_user, file=file)
    except UploadTooLargeError as exc:
        logger.warning(
            "上传文件超过大小限制",
            extra={"file_name": file.filename, "content_type": file.content_type},
        )
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="File size exceeds max_upload_bytes",
        ) from exc
    except UploadValidationError as exc:
        logger.warning(
            "上传文件校验失败",
            extra={"file_name": file.filename, "reason": str(exc)},
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (UploadStorageError, UploadMetadataError) as exc:
        logger.error(
            "上传文件存储或元数据保存失败",
            extra={"file_name": file.filename, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store uploaded file",
        ) from exc

    return UploadedFileRead.model_validate(record, from_attributes=True)
