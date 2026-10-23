"""系统级模型服务元数据；密钥仅持有密文。"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Column, DateTime, Integer, String, Text, text
from sqlmodel import Field, SQLModel

from app.models.user import utc_now

MODEL_KINDS = ("chat", "embedding", "rerank", "query_rewrite")
KIND_CHECK = "kind IN ('chat', 'embedding', 'rerank', 'query_rewrite')"


class ModelProfile(SQLModel, table=True):
    __tablename__ = "model_profiles"
    __table_args__ = (CheckConstraint(KIND_CHECK, name="ck_model_profiles_kind"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(max_length=100)
    kind: str = Field(sa_column=Column(String(32), nullable=False, index=True))
    base_url: str = Field(max_length=2048)
    model: str = Field(max_length=255)
    api_key_encrypted: str | None = Field(default=None, repr=False, sa_column=Column(Text))
    enabled: bool = True
    timeout_seconds: float = 15
    max_retries: int = 1
    dimensions: int | None = None
    api_format: str | None = None
    revision: int = Field(
        default=1, sa_column=Column(Integer, nullable=False, server_default=text("1"))
    )
    created_at: datetime = Field(
        default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = Field(
        default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class ModelBinding(SQLModel, table=True):
    __tablename__ = "model_bindings"
    __table_args__ = (CheckConstraint(KIND_CHECK, name="ck_model_bindings_kind"),)

    kind: str = Field(primary_key=True, max_length=32)
    profile_id: UUID | None = Field(default=None, foreign_key="model_profiles.id")
    revision: int = 0
