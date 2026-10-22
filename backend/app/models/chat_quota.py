"""Persistent per-account rolling chat limits and admission reservations."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Column, DateTime, Index
from sqlmodel import Field, SQLModel

from app.models.user import utc_now


class UserChatLimit(SQLModel, table=True):
    __tablename__ = "user_chat_limits"
    __table_args__ = (CheckConstraint("hourly_limit > 0", name="ck_user_chat_limits_positive"),)

    user_id: UUID = Field(primary_key=True, foreign_key="users.id")
    hourly_limit: int


class ChatUsage(SQLModel, table=True):
    __tablename__ = "chat_usage"
    __table_args__ = (Index("ix_chat_usage_user_created", "user_id", "created_at"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id")
    created_at: datetime = Field(
        default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
