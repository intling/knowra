from contextlib import suppress
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlmodel import Session

from app.core.logging import get_logger
from app.models.uploaded_file import UploadedFile
from app.models.user import User

logger = get_logger(__name__)

CHUNK_SIZE = 1024 * 1024


class UploadValidationError(Exception):
    pass


class UploadTooLargeError(UploadValidationError):
    pass


class UploadStorageError(Exception):
    pass


class UploadMetadataError(Exception):
    pass


@dataclass(frozen=True)
class StoredFile:
    byte_size: int
    checksum_sha256: str


class LocalFileStorage:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)

    def path_for(self, storage_key: str) -> Path:
        path_parts = PurePosixPath(storage_key).parts
        if not path_parts or any(part in {"", ".", ".."} for part in path_parts):
            raise UploadStorageError("Invalid storage key")

        return self.root_dir.joinpath(*path_parts)

    def write(self, storage_key: str, source: BinaryIO, max_bytes: int) -> StoredFile:
        destination = self.path_for(storage_key)
        digest = sha256()
        byte_size = 0

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("wb") as target:
                while chunk := source.read(CHUNK_SIZE):
                    byte_size += len(chunk)
                    if byte_size > max_bytes:
                        raise UploadTooLargeError("File size exceeds max_upload_bytes")

                    digest.update(chunk)
                    target.write(chunk)
        except UploadTooLargeError:
            self.delete(storage_key)
            raise
        except OSError as exc:
            self.delete(storage_key)
            logger.error(
                "存储写入失败",
                extra={"storage_key": storage_key, "error": str(exc)},
            )
            raise UploadStorageError("Failed to write uploaded file") from exc

        return StoredFile(byte_size=byte_size, checksum_sha256=digest.hexdigest())

    def delete(self, storage_key: str) -> None:
        with suppress(OSError):
            self.path_for(storage_key).unlink(missing_ok=True)


class UploadService:
    def __init__(
        self,
        *,
        session: Session,
        storage: LocalFileStorage,
        max_upload_bytes: int,
        allowed_content_types: set[str],
    ) -> None:
        self.session = session
        self.storage = storage
        self.max_upload_bytes = max_upload_bytes
        self.allowed_content_types = allowed_content_types

    def create_upload(self, *, current_user: User, file: UploadFile) -> UploadedFile:
        content_type = file.content_type
        if content_type and content_type not in self.allowed_content_types:
            logger.warning(
                "不支持的文件类型",
                extra={
                    "content_type": content_type,
                    "allowed_types": sorted(self.allowed_content_types),
                },
            )
            raise UploadValidationError("Unsupported content type")

        upload_id = uuid4()
        storage_key = self.generate_storage_key(
            owner_user_id=current_user.id,
            upload_id=upload_id,
            original_filename=file.filename,
        )

        try:
            stored_file = self.storage.write(storage_key, file.file, self.max_upload_bytes)
        except UploadTooLargeError:
            raise

        logger.info(
            "文件写入存储成功",
            extra={
                "upload_id": str(upload_id),
                "byte_size": stored_file.byte_size,
                "checksum_sha256": stored_file.checksum_sha256,
            },
        )

        if stored_file.byte_size == 0:
            self.storage.delete(storage_key)
            logger.warning("上传文件为空", extra={"upload_id": str(upload_id)})
            raise UploadValidationError("Uploaded file is empty")

        record = UploadedFile(
            id=upload_id,
            owner_user_id=current_user.id,
            original_filename=file.filename or "uploaded-file",
            content_type=content_type,
            byte_size=stored_file.byte_size,
            storage_key=storage_key,
            checksum_sha256=stored_file.checksum_sha256,
            status="stored",
            error_message=None,
        )
        self.session.add(record)

        try:
            self.session.commit()
            self.session.refresh(record)
        except Exception as exc:
            self.session.rollback()
            self.storage.delete(storage_key)
            logger.error(
                "数据库提交失败，已回滚",
                extra={"upload_id": str(upload_id), "error": str(exc)},
            )
            raise UploadMetadataError("Failed to save upload metadata") from exc

        logger.info("上传记录创建成功", extra={"upload_id": str(upload_id)})
        return record

    @staticmethod
    def generate_storage_key(
        *,
        owner_user_id: UUID,
        upload_id: UUID,
        original_filename: str | None,
    ) -> str:
        extension = safe_extension(original_filename)
        return f"uploads/{owner_user_id}/{upload_id}/original{extension}"


def safe_extension(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if not suffix or len(suffix) > 16:
        return ".bin"

    safe_chars = suffix[1:]
    if not safe_chars.isalnum():
        return ".bin"

    return suffix
