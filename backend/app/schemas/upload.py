from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import UtcDateTime


class UploadedFileRead(BaseModel):
    id: UUID
    owner_user_id: UUID
    original_filename: str
    content_type: str | None
    byte_size: int
    storage_key: str
    checksum_sha256: str | None
    status: str
    error_message: str | None
    deleted_at: UtcDateTime | None
    created_at: UtcDateTime
    updated_at: UtcDateTime
