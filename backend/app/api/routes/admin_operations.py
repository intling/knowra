"""显式管理员命名空间下的运行元数据与不可变审计。"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import SessionDep, require_permission
from app.core.config import Settings, get_settings
from app.core.permissions import AUDIT_READ, OPERATIONS_READ
from app.models.user import User
from app.schemas.admin_operations import (
    AdminJobDetail,
    AdminJobPage,
    AdminOverview,
    AuditAction,
    AuditEventPage,
    AuditResult,
    JobKind,
    JobStatus,
    SystemStatus,
)
from app.services import admin_operations as service
from app.services.admin_system import system_status

router = APIRouter(prefix="/admin", tags=["admin-operations"])
OperationsDep = Annotated[User, Depends(require_permission(OPERATIONS_READ))]
AuditDep = Annotated[User, Depends(require_permission(AUDIT_READ))]
SettingsDep = Annotated[Settings, Depends(get_settings)]
Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]
Start = Annotated[datetime | None, Query(alias="from")]
End = Annotated[datetime | None, Query(alias="to")]


@router.get("/jobs", response_model=AdminJobPage)
def read_jobs(
    admin: OperationsDep,
    session: SessionDep,
    kind: JobKind | None = None,
    status: JobStatus | None = None,
    owner_user_id: UUID | None = None,
    start: Start = None,
    end: End = None,
    offset: Offset = 0,
    limit: Limit = 20,
):
    start, end = service.time_range(start, end)
    return service.list_jobs(
        session,
        start=start,
        end=end,
        kind=kind,
        status=status,
        owner_user_id=owner_user_id,
        offset=offset,
        limit=limit,
    )


@router.get("/jobs/{kind}/{job_id}", response_model=AdminJobDetail)
def read_job(kind: JobKind, job_id: UUID, admin: OperationsDep, session: SessionDep):
    return service.job_detail(session, kind, job_id)


@router.get("/audit-events", response_model=AuditEventPage)
def read_audit(
    admin: AuditDep,
    session: SessionDep,
    actor_user_id: UUID | None = None,
    action: AuditAction | None = None,
    result: AuditResult | None = None,
    trace_id: Annotated[str | None, Query(max_length=64)] = None,
    start: Start = None,
    end: End = None,
    offset: Offset = 0,
    limit: Limit = 20,
):
    start, end = service.time_range(start, end, days=7)
    return service.list_audit_events(
        session,
        start=start,
        end=end,
        actor_user_id=actor_user_id,
        action=action,
        result=result,
        trace_id=trace_id,
        offset=offset,
        limit=limit,
    )


@router.get("/overview", response_model=AdminOverview)
def read_overview(admin: OperationsDep, session: SessionDep, request: Request):
    return service.overview(session, getattr(request.app.state, "document_model_readiness", None))


@router.get("/system/status", response_model=SystemStatus)
async def read_system(
    admin: OperationsDep, session: SessionDep, settings: SettingsDep, request: Request
):
    state = request.app.state
    return await system_status(
        session,
        settings,
        getattr(state, "document_model_readiness", None),
        state.application_shutdown_state,
        state.admin_instance_id,
    )
