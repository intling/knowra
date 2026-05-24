from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, String
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    display_name: str = Field(sa_column=Column(String(100), nullable=False))
    email: str | None = Field(
        default=None,
        sa_column=Column(String(255), nullable=True, unique=True),
    )
    avatar_url: str | None = Field(default=None, sa_column=Column(String(1024), nullable=True))
    status: str = Field(default="active", sa_column=Column(String(32), nullable=False))
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
