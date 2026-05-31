from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlmodel import Field, SQLModel

from app.models.user import utc_now


class UploadedFile(SQLModel, table=True):
    __tablename__ = "uploaded_files"
    __table_args__ = (
        Index("ix_uploaded_files_owner_user_id", "owner_user_id"),
        Index("ix_uploaded_files_status", "status"),
        Index("ix_uploaded_files_created_at", "created_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    owner_user_id: UUID = Field(
        sa_column=Column(ForeignKey("users.id"), nullable=False),
    )
    original_filename: str = Field(sa_column=Column(String(255), nullable=False))
    content_type: str | None = Field(default=None, sa_column=Column(String(255), nullable=True))
    byte_size: int = Field(sa_column=Column(Integer, nullable=False))
    storage_key: str = Field(sa_column=Column(String(1024), nullable=False, unique=True))
    checksum_sha256: str | None = Field(default=None, sa_column=Column(String(64), nullable=True))
    status: str = Field(default="stored", sa_column=Column(String(32), nullable=False))
    error_message: str | None = Field(default=None, sa_column=Column(String(1024), nullable=True))
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
