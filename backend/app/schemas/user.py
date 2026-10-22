from uuid import UUID

from pydantic import BaseModel, computed_field

from app.core.permissions import permissions_for
from app.schemas.common import UtcDateTime


class UserRead(BaseModel):
    id: UUID
    display_name: str
    email: str | None
    avatar_url: str | None
    status: str
    role: str
    deleted_at: UtcDateTime | None
    created_at: UtcDateTime
    updated_at: UtcDateTime

    @computed_field
    @property
    def permissions(self) -> list[str]:
        return permissions_for(self.role)
