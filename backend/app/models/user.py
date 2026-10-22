from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Column, DateTime, String
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC)


class User(SQLModel, table=True):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'member', 'viewer')", name="ck_users_role"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    display_name: str = Field(sa_column=Column(String(100), nullable=False))
    email: str | None = Field(
        default=None,
        sa_column=Column(String(255), nullable=True, unique=True),
    )
    avatar_url: str | None = Field(default=None, sa_column=Column(String(1024), nullable=True))
    status: str = Field(default="active", sa_column=Column(String(32), nullable=False))
    role: str = Field(
        default="member", sa_column=Column(String(16), nullable=False, server_default="member")
    )
    deleted_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class UserCredential(SQLModel, table=True):
    __tablename__ = "user_credentials"

    user_id: UUID = Field(primary_key=True, foreign_key="users.id")
    password_hash: str = Field(sa_column=Column(String(1024), nullable=False))
    created_at: datetime = Field(
        default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = Field(
        default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class UserSession(SQLModel, table=True):
    __tablename__ = "user_sessions"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    token_hash: str = Field(sa_column=Column(String(64), nullable=False, unique=True))
    created_at: datetime = Field(
        default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    revoked_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
