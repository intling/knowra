from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.schemas.common import UtcDateTime
from app.schemas.user import UserRead


class RegisterRequest(BaseModel):
    email: str
    display_name: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class ProfileUpdate(BaseModel):
    display_name: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class AdminUserUpdate(BaseModel):
    role: Literal["admin", "member", "viewer"] | None = None
    status: Literal["active", "disabled"] | None = None


class AdminUserCreate(BaseModel):
    email: str
    display_name: str
    password: str
    role: Literal["admin", "member", "viewer"] = "member"
    status: Literal["active", "disabled"] = "active"


class AdminPasswordReset(BaseModel):
    new_password: str


class UserPage(BaseModel):
    items: list[UserRead]
    total: int
    offset: int
    limit: int


class ChatLimitSnapshot(BaseModel):
    hourly_limit: int | None
    occupied_slots: int | None
    remaining: int | None
    window_seconds: int = 3600
    observed_at: UtcDateTime


class ChatLimitUpdate(BaseModel):
    hourly_limit: Annotated[int, Field(strict=True, ge=1, le=100000)] | None


class SessionRevokeResult(BaseModel):
    revoked_count: int


class AdminUserDetail(BaseModel):
    user: UserRead
    active_session_count: int
    chat_limit: ChatLimitSnapshot
