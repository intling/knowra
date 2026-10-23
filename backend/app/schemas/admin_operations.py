"""只读运维 API 的安全字段白名单。"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import UtcDateTime

JobKind = Literal["parse", "chunk", "embedding"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "superseded", "unknown"]
ComponentStatus = Literal["ok", "degraded", "unavailable", "unknown", "disabled"]
AuditAction = Literal[
    "user.create",
    "user.update",
    "user.reset_password",
    "user.delete",
    "user.chat_limit.update",
    "user.sessions.revoke",
    "model.create",
    "model.update",
    "model.activate",
    "model.deactivate",
    "model.delete",
    "model.test",
]
AuditResult = Literal["success", "denied", "failed"]


class AdminJobRead(BaseModel):
    id: UUID
    kind: JobKind
    uploaded_file_id: UUID
    owner_user_id: UUID
    owner_label: str
    status: JobStatus
    attempt_count: int
    created_at: UtcDateTime
    started_at: UtcDateTime | None
    finished_at: UtcDateTime | None
    duration_ms: float | None
    item_count: int | None
    error_code: str | None
    error_detail: str | None


class AdminJobPage(BaseModel):
    items: list[AdminJobRead]
    total: int
    offset: int
    limit: int


class AdminJobDetail(BaseModel):
    job: AdminJobRead
    timeline: list[AdminJobRead]
    missing_kinds: list[JobKind]


class AuditEventRead(BaseModel):
    id: UUID
    actor_user_id: UUID
    action: AuditAction
    resource_type: Literal["user", "model"]
    resource_id: UUID
    result: AuditResult
    changes_json: dict
    error_code: str | None
    trace_id: str
    created_at: UtcDateTime


class AuditEventPage(BaseModel):
    items: list[AuditEventRead]
    total: int
    offset: int
    limit: int


class StatusComponent(BaseModel):
    name: str
    status: ComponentStatus
    detail: str


class SystemStatus(BaseModel):
    checked_at: UtcDateTime
    scope: Literal["instance"] = "instance"
    instance_id: str
    components: list[StatusComponent]


class UserTotals(BaseModel):
    status: ComponentStatus
    total: int | None
    active: int | None
    disabled: int | None


class UploadTotals(BaseModel):
    status: ComponentStatus
    total: int | None
    logical_bytes: int | None


class JobTotals(BaseModel):
    kind: JobKind
    status: ComponentStatus
    queued: int | None
    running: int | None
    succeeded_24h: int | None
    failed_24h: int | None
    success_rate_24h: float | None


class AttentionItem(BaseModel):
    code: str
    detail: str
    href: str
    count: int | None = None


class AdminOverview(BaseModel):
    snapshot_at: UtcDateTime
    users: UserTotals
    uploads: UploadTotals
    jobs_by_kind: list[JobTotals]
    attention_items: list[AttentionItem]
