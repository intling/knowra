from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import UtcDateTime


class UserRead(BaseModel):
    id: UUID
    display_name: str
    email: str | None
    avatar_url: str | None
    status: str
    deleted_at: UtcDateTime | None
    created_at: UtcDateTime
    updated_at: UtcDateTime
