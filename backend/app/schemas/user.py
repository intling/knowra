from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, field_serializer


class UserRead(BaseModel):
    id: UUID
    display_name: str
    email: str | None
    avatar_url: str | None
    status: str
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("deleted_at", "created_at", "updated_at")
    def serialize_datetime(self, value: datetime | None) -> str | None:
        if value is None:
            return None

        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)

        return value.isoformat().replace("+00:00", "Z")
