"""后台管理审计与模型诊断历史；不持有凭据或私有资料内容。"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, ForeignKey, Index, String, Uuid
from sqlmodel import Field, SQLModel

from app.models.user import utc_now


class AdminAuditEvent(SQLModel, table=True):
    __tablename__ = "admin_audit_events"
    __table_args__ = (
        CheckConstraint("result IN ('success', 'denied', 'failed')", name="ck_admin_audit_result"),
        Index("ix_admin_audit_created_id", "created_at", "id"),
        Index("ix_admin_audit_actor_created", "actor_user_id", "created_at"),
        Index("ix_admin_audit_action_created", "action", "created_at"),
        Index("ix_admin_audit_trace_id", "trace_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    actor_user_id: UUID = Field(foreign_key="users.id")
    action: str = Field(max_length=64)
    resource_type: str = Field(max_length=32)
    resource_id: UUID
    result: str = Field(max_length=16)
    changes_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    error_code: str | None = Field(default=None, max_length=64)
    trace_id: str = Field(max_length=64)
    created_at: datetime = Field(
        default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class ModelProbeResult(SQLModel, table=True):
    __tablename__ = "model_probe_results"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'passed', 'failed', 'interrupted')",
            name="ck_model_probe_status",
        ),
        Index("ix_model_probe_profile_started", "profile_id", "started_at"),
        Index("ix_model_probe_lease_expires", "lease_expires_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    profile_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            Uuid(), ForeignKey("model_profiles.id", ondelete="SET NULL"), nullable=True
        ),
    )
    profile_revision: int
    actor_user_id: UUID = Field(foreign_key="users.id")
    status: str = Field(default="running", sa_column=Column(String(32), nullable=False))
    code: str | None = Field(default=None, max_length=64)
    latency_ms: float | None = None
    started_at: datetime = Field(
        default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    finished_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    lease_expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    trace_id: str = Field(max_length=64)
