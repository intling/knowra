"""跨账号的只读运维投影；不加载资料正文、配置 JSON 或原始错误。"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import case, func, literal, select, union_all
from sqlmodel import Session

from app.core.errors import AppError
from app.core.logging import get_logger
from app.models.admin_operations import AdminAuditEvent
from app.models.document_chunking import DocumentChunkJob
from app.models.document_embedding import DocumentEmbeddingJob
from app.models.document_parsing import DocumentParseJob, ParsedDocument
from app.models.uploaded_file import UploadedFile
from app.models.user import User, utc_now
from app.schemas.admin_operations import (
    AdminJobDetail,
    AdminJobPage,
    AdminJobRead,
    AdminOverview,
    AttentionItem,
    AuditEventPage,
    AuditEventRead,
    JobTotals,
    UploadTotals,
    UserTotals,
)
from app.services.admin_audit import CHANGE_FIELDS
from app.services.model_configuration import PROBE_DETAILS

logger = get_logger(__name__)
JOB_MODELS = {
    "parse": DocumentParseJob,
    "chunk": DocumentChunkJob,
    "embedding": DocumentEmbeddingJob,
}
SAFE_JOB_ERRORS = {
    "model_not_ready": "处理模型尚未就绪",
    "document_model_unavailable": "文档模型暂不可用",
    "embedding_failed": "向量化处理失败",
    "chunking_failed": "分块处理失败",
    "parse_failed": "解析处理失败",
    "shutdown_interrupted": "应用关闭导致任务中断",
    "processing_failed": "处理失败，请根据任务标识和时间排查服务日志",
}
SAFE_AUDIT_ERRORS = {
    "last_admin",
    "forbidden",
    "cannot_disable_self",
    "cannot_delete_self",
    "cannot_reset_self",
    "cannot_revoke_self_sessions",
    "user_not_found",
    "model_not_found",
    "model_in_use",
    "model_disabled",
    "model_not_active",
    "embedding_index_conflict",
    "model_revision_conflict",
    "model_test_rate_limited",
    "model_secret_unavailable",
    "admin_dependency_unavailable",
    "admin_audit_unavailable",
    "admin_operation_failed",
    "empty_update",
    "invalid_model_configuration",
    "email_conflict",
    "weak_password",
    "invalid_email",
}


def time_range(start: datetime | None, end: datetime | None, *, days: int = 1):
    end = end or utc_now()
    start = start or end - timedelta(days=days)
    if (
        start.tzinfo is None
        or end.tzinfo is None
        or start >= end
        or end - start > timedelta(days=31)
    ):
        raise AppError(
            422, "invalid_time_range", "请使用带时区的起止时间，结束晚于开始且范围不超过 31 天"
        )
    return start.astimezone(UTC), end.astimezone(UTC)


def jobs_projection():
    queries = []
    for kind, model in JOB_MODELS.items():
        uploaded = model.uploaded_file_id if kind == "parse" else ParsedDocument.uploaded_file_id
        count = (
            model.chunk_count
            if kind == "chunk"
            else model.embedding_count
            if kind == "embedding"
            else literal(None)
        )
        query = select(
            model.id.label("id"),
            literal(kind).label("kind"),
            uploaded.label("uploaded_file_id"),
            model.owner_user_id,
            User.deleted_at.label("owner_deleted"),
            model.status,
            model.attempt_count,
            model.created_at,
            model.started_at,
            model.finished_at,
            count.label("item_count"),
            model.error_code,
        ).select_from(model)
        if kind != "parse":
            query = query.join(ParsedDocument, ParsedDocument.id == model.parsed_document_id)
        if kind == "embedding":
            query = query.join(
                DocumentChunkJob,
                (DocumentChunkJob.id == model.chunk_job_id)
                & (DocumentChunkJob.parsed_document_id == model.parsed_document_id),
            )
        query = query.join(User, User.id == model.owner_user_id)
        queries.append(query)
    return union_all(*queries).subquery("admin_jobs")


def _utc(value):
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


def job_read(row):
    data = dict(row)
    data["owner_label"] = (
        "已删除账号" if data.pop("owner_deleted") else f"账号 {str(data['owner_user_id'])[:8]}"
    )
    started, finished = _utc(data["started_at"]), _utc(data["finished_at"])
    data["duration_ms"] = (
        max(0, ((finished or utc_now()) - started).total_seconds() * 1000) if started else None
    )
    status = data["status"]
    data["status"] = (
        status
        if status in {"queued", "running", "succeeded", "failed", "superseded"}
        else "unknown"
    )
    code = data["error_code"]
    data["error_code"] = (
        code if code in SAFE_JOB_ERRORS else "processing_failed" if status == "failed" else None
    )
    data["error_detail"] = SAFE_JOB_ERRORS.get(data["error_code"])
    return AdminJobRead(**data)


def list_jobs(
    session: Session, *, start, end, kind=None, status=None, owner_user_id=None, offset=0, limit=20
):
    table = jobs_projection()
    filters = [table.c.created_at >= start, table.c.created_at < end]
    for field, value in [("kind", kind), ("status", status), ("owner_user_id", owner_user_id)]:
        if value is not None:
            filters.append(table.c[field] == value)
    total = session.execute(select(func.count()).select_from(table).where(*filters)).scalar_one()
    rows = (
        session.execute(
            select(table)
            .where(*filters)
            .order_by(table.c.created_at.desc(), table.c.id.desc())
            .offset(offset)
            .limit(limit)
        )
        .mappings()
        .all()
    )
    return AdminJobPage(items=[job_read(r) for r in rows], total=total, offset=offset, limit=limit)


def job_detail(session, kind, job_id):
    table = jobs_projection()
    row = (
        session.execute(select(table).where(table.c.kind == kind, table.c.id == job_id))
        .mappings()
        .first()
    )
    if row is None:
        raise AppError(404, "admin_job_not_found", "处理任务不存在")
    rows = (
        session.execute(
            select(table)
            .where(table.c.uploaded_file_id == row["uploaded_file_id"])
            .order_by(table.c.created_at, table.c.id)
        )
        .mappings()
        .all()
    )
    return AdminJobDetail(
        job=job_read(row),
        timeline=[job_read(r) for r in rows],
        missing_kinds=[k for k in JOB_MODELS if k not in {r["kind"] for r in rows}],
    )


def user_totals(session):
    row = session.execute(
        select(
            func.count(),
            func.sum(case((User.status == "active", 1), else_=0)),
            func.sum(case((User.status == "disabled", 1), else_=0)),
        ).where(User.deleted_at.is_(None))
    ).one()
    return UserTotals(status="ok", total=row[0], active=row[1] or 0, disabled=row[2] or 0)


def upload_totals(session):
    row = session.execute(
        select(func.count(), func.coalesce(func.sum(UploadedFile.byte_size), 0))
        .select_from(UploadedFile)
        .join(User, User.id == UploadedFile.owner_user_id)
        .where(UploadedFile.deleted_at.is_(None), User.deleted_at.is_(None))
    ).one()
    return UploadTotals(status="ok", total=row[0], logical_bytes=row[1])


def job_totals(session, kind, now):
    model = JOB_MODELS[kind]
    cutoff = now - timedelta(hours=24)

    def count(status, completed=False):
        condition = model.status == status
        if completed:
            condition = condition & (model.finished_at >= cutoff) & (model.finished_at < now)
        return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)

    row = session.execute(
        select(count("queued"), count("running"), count("succeeded", True), count("failed", True))
    ).one()
    return JobTotals(
        kind=kind,
        status="ok",
        queued=row[0],
        running=row[1],
        succeeded_24h=row[2],
        failed_24h=row[3],
        success_rate_24h=row[2] / (row[2] + row[3]) if row[2] + row[3] else None,
    )


def _stat(session, name, call, fallback):
    try:
        with session.begin_nested():
            return call()
    except Exception:
        logger.warning("管理统计区块不可用", component=name)
        return fallback


def overview(session, readiness):
    now = utc_now()
    users = _stat(
        session,
        "users",
        lambda: user_totals(session),
        UserTotals(status="unavailable", total=None, active=None, disabled=None),
    )
    uploads = _stat(
        session,
        "uploads",
        lambda: upload_totals(session),
        UploadTotals(status="unavailable", total=None, logical_bytes=None),
    )
    jobs = [
        _stat(
            session,
            kind,
            lambda k=kind: job_totals(session, k, now),
            JobTotals(
                kind=kind,
                status="unavailable",
                queued=None,
                running=None,
                succeeded_24h=None,
                failed_24h=None,
                success_rate_24h=None,
            ),
        )
        for kind in JOB_MODELS
    ]
    attention = [
        AttentionItem(
            code="failed_jobs",
            detail=(
                f"{dict(parse='解析', chunk='分块', embedding='向量化')[j.kind]}"
                "阶段最近 24 小时有失败任务"
            ),
            count=j.failed_24h,
            href=f"/admin/jobs?kind={j.kind}&status=failed",
        )
        for j in jobs
        if j.failed_24h
    ]
    if getattr(readiness, "status", "unknown") not in {"ready", "skipped"}:
        attention.append(
            AttentionItem(
                code="document_models_not_ready",
                detail="文档模型未就绪或状态未知",
                href="/admin/system",
            )
        )
    return AdminOverview(
        snapshot_at=now, users=users, uploads=uploads, jobs_by_kind=jobs, attention_items=attention
    )


def _safe_value(field, value):
    if value is None:
        return True
    if field == "role":
        return value in {"admin", "member", "viewer"} if isinstance(value, str) else False
    if field == "status":
        return (
            value in {"active", "disabled", "passed", "failed", "interrupted"}
            if isinstance(value, str)
            else False
        )
    if field in {"enabled", "deleted"}:
        return type(value) is bool
    if field in {
        "hourly_limit",
        "revision",
        "binding_revision",
        "profile_revision",
        "dimensions",
        "max_retries",
    }:
        return type(value) is int and value >= 0
    if field in {"timeout_seconds", "latency_ms"}:
        return type(value) in (int, float) and value >= 0
    if field == "kind":
        return (
            value in {"chat", "embedding", "rerank", "query_rewrite"}
            if isinstance(value, str)
            else False
        )
    if field == "code":
        return value in PROBE_DETAILS if isinstance(value, str) else False
    if field == "api_format":
        return value in {"compatible", "dashscope"} if isinstance(value, str) else False
    if field == "default_profile_id":
        try:
            UUID(value)
            return True
        except TypeError, ValueError, AttributeError:
            return False
    return field == "model" and isinstance(value, str) and len(value) <= 255 and "\n" not in value


def safe_changes(row):
    if row.result != "success":
        return {}
    result = {}
    for field, value in row.changes_json.items():
        if (
            (
                field in {"secret_changed", "endpoint_changed"}
                and row.action in {"model.create", "model.update", "model.delete"}
                and type(value) is bool
            )
            or field in CHANGE_FIELDS.get(row.action, ())
            and (
                (field == "revoked_count" and type(value) is int and value >= 0)
                or (row.action == "model.test" and _safe_value(field, value))
                or (
                    isinstance(value, dict)
                    and set(value) == {"before", "after"}
                    and all(_safe_value(field, v) for v in value.values())
                )
            )
        ):
            result[field] = value
    return result


def list_audit_events(
    session,
    *,
    start,
    end,
    actor_user_id=None,
    action=None,
    result=None,
    trace_id=None,
    offset=0,
    limit=20,
):
    model = AdminAuditEvent
    filters = [
        model.created_at >= start,
        model.created_at < end,
        model.action.in_(list(CHANGE_FIELDS)),
    ]
    for field, value in [
        ("actor_user_id", actor_user_id),
        ("action", action),
        ("result", result),
        ("trace_id", trace_id),
    ]:
        if value is not None:
            filters.append(getattr(model, field) == value)
    total = session.execute(select(func.count()).select_from(model).where(*filters)).scalar_one()
    rows = (
        session.execute(
            select(model)
            .where(*filters)
            .order_by(model.created_at.desc(), model.id.desc())
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    items = [
        AuditEventRead(
            **r.model_dump(exclude={"changes_json", "error_code"}),
            changes_json=safe_changes(r),
            error_code=r.error_code
            if r.error_code in SAFE_AUDIT_ERRORS
            else "admin_operation_failed"
            if r.error_code
            else None,
        )
        for r in rows
    ]
    return AuditEventPage(items=items, total=total, offset=offset, limit=limit)
