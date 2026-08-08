from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
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
PPTX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
PPTX_BROWSER_COMPAT_CONTENT_TYPES = {"application/vnd.ms-powerpoint"}


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
                storage_key=storage_key,
                error=str(exc),
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

    def create_upload(self, *, current_user: User, file: UploadFile, force: bool = False) -> tuple[UploadedFile, bool]:
        content_type = file.content_type
        if not self._is_allowed_content_type(content_type, file.filename):
            logger.warning(
                "不支持的文件类型",
                content_type=content_type,
                allowed_types=sorted(self.allowed_content_types),
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
            upload_id=str(upload_id),
            byte_size=stored_file.byte_size,
            checksum_sha256=stored_file.checksum_sha256,
        )

        if stored_file.byte_size == 0:
            self.storage.delete(storage_key)
            logger.warning("上传文件为空", upload_id=str(upload_id))
            raise UploadValidationError("Uploaded file is empty")

        # ── 内容去重：基于 owner_user_id + checksum_sha256 ──────────
        existing = self._find_active_duplicate(current_user.id, stored_file.checksum_sha256)
        if existing is not None:
            if not force:
                # 幂等模式：清理临时文件，直接返回已有记录
                self.storage.delete(storage_key)
                logger.info(
                    "检测到重复上传，幂等返回已有记录",
                    existing_upload_id=str(existing.id),
                    checksum_sha256=stored_file.checksum_sha256,
                )
                return existing, False
            else:
                # 强制替换模式：软删除旧记录（含其下游 parsed/chunks/embeddings 由搜索层 filtered 屏蔽）
                self._soft_delete_duplicate(current_user.id, stored_file.checksum_sha256)
                logger.info(
                    "强制替换模式：已软删除旧文件记录",
                    checksum_sha256=stored_file.checksum_sha256,
                )

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
                upload_id=str(upload_id),
                error=str(exc),
            )
            raise UploadMetadataError("Failed to save upload metadata") from exc

        logger.info("上传记录创建成功", upload_id=str(upload_id))
        return record, True

    @staticmethod
    def generate_storage_key(
        *,
        owner_user_id: UUID,
        upload_id: UUID,
        original_filename: str | None,
    ) -> str:
        extension = safe_extension(original_filename)
        return f"uploads/{owner_user_id}/{upload_id}/original{extension}"

    def _is_allowed_content_type(self, content_type: str | None, filename: str | None) -> bool:
        if not content_type or content_type in self.allowed_content_types:
            return True

        return (
            content_type in PPTX_BROWSER_COMPAT_CONTENT_TYPES
            and safe_extension(filename) == ".pptx"
            and PPTX_CONTENT_TYPE in self.allowed_content_types
        )

    def _find_active_duplicate(self, owner_user_id: UUID, checksum_sha256: str) -> UploadedFile | None:
        """查找同一用户下、内容哈希相同且未被软删除的已有上传记录。"""
        from sqlmodel import select as sm_select

        return self.session.exec(
            sm_select(UploadedFile).where(
                UploadedFile.owner_user_id == owner_user_id,
                UploadedFile.checksum_sha256 == checksum_sha256,
                UploadedFile.deleted_at.is_(None),
            )
        ).first()

    def _soft_delete_duplicate(self, owner_user_id: UUID, checksum_sha256: str) -> None:
        """软删除同一用户下指定内容哈希的所有活跃记录。

        软删除后，下游搜索层会自动过滤这些文件对应的向量，
        kb_fingerprint 也会因 embedding 更新检测到变化。
        """
        from sqlmodel import select as sm_select

        now = datetime.now(timezone.utc)
        duplicates = self.session.exec(
            sm_select(UploadedFile).where(
                UploadedFile.owner_user_id == owner_user_id,
                UploadedFile.checksum_sha256 == checksum_sha256,
                UploadedFile.deleted_at.is_(None),
            )
        ).all()
        for record in duplicates:
            record.deleted_at = now
            record.updated_at = now
            self.session.add(record)
        if duplicates:
            self.session.flush()
            logger.info(
                "批量软删除重复文件记录",
                checksum_sha256=checksum_sha256,
                count=len(duplicates),
            )


def safe_extension(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if not suffix or len(suffix) > 16:
        return ".bin"

    safe_chars = suffix[1:]
    if not safe_chars.isalnum():
        return ".bin"

    return suffix
