from typing import Literal

from pydantic import BaseModel

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
