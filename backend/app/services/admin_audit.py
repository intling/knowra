"""管理员写操作的事务边界与按动作裁剪的持久化审计。"""

from collections.abc import Generator, Mapping
from contextlib import contextmanager
from uuid import UUID

from sqlmodel import Session

from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.trace_context import get_trace_id
from app.models.admin_operations import AdminAuditEvent
from app.models.user import User

logger = get_logger(__name__)

MODEL_FIELDS = frozenset(
    {
        "kind",
        "model",
        "enabled",
        "timeout_seconds",
        "max_retries",
        "dimensions",
        "api_format",
        "revision",
    }
)
CHANGE_FIELDS = {
    "user.create": frozenset({"role", "status"}),
    "user.update": frozenset({"role", "status"}),
    "user.reset_password": frozenset(),
    "user.delete": frozenset({"status", "deleted"}),
    "user.chat_limit.update": frozenset({"hourly_limit"}),
    "user.sessions.revoke": frozenset({"revoked_count"}),
    "model.create": MODEL_FIELDS,
    "model.update": MODEL_FIELDS,
    "model.delete": MODEL_FIELDS,
    "model.activate": frozenset({"kind", "default_profile_id", "binding_revision"}),
    "model.deactivate": frozenset({"kind", "default_profile_id", "binding_revision"}),
    "model.test": frozenset({"profile_revision", "status", "code", "latency_ms"}),
}


class AuditChanges:
    def __init__(self, action: str) -> None:
        self.action = action
        self.values: dict = {}

    def capture(
        self,
        before: Mapping,
        after: Mapping,
        *,
        secret_changed: bool = False,
        endpoint_changed: bool = False,
    ) -> None:
        # 只从服务器提供的状态快照提取动作字段，不复制请求、显示名、地址或秘密。
        for field in CHANGE_FIELDS[self.action]:
            previous, current = before.get(field), after.get(field)
            if previous != current:
                self.values[field] = {
                    "before": str(previous) if isinstance(previous, UUID) else previous,
                    "after": str(current) if isinstance(current, UUID) else current,
                }
        if self.action in {"model.create", "model.update", "model.delete"}:
            if secret_changed:
                self.values["secret_changed"] = True
            if endpoint_changed:
                self.values["endpoint_changed"] = True


def _record_failure(session: Session, identity: dict, error: AppError) -> None:
    # 调用方已回滚业务事务。独立短事务失败时仅记录安全标识，不复制数据库异常。
    try:
        session.add(
            AdminAuditEvent(
                **identity,
                result="denied" if error.status_code < 500 else "failed",
                error_code=error.code,
                changes_json={},
            )
        )
        session.commit()
    except Exception:
        session.rollback()
        logger.warning("管理失败审计写入失败", **identity, error_code=error.code)


@contextmanager
def admin_operation(
    session: Session, actor: User, action: str, resource_id: UUID
) -> Generator[AuditChanges]:
    if action not in CHANGE_FIELDS:
        raise ValueError("未知管理审计动作")
    identity = {
        "actor_user_id": actor.id,
        "action": action,
        "resource_type": action.split(".")[0],
        "resource_id": resource_id,
        "trace_id": get_trace_id(),
    }
    changes = AuditChanges(action)
    try:
        yield changes
        session.flush()
    except AppError as error:
        session.rollback()
        _record_failure(session, identity, error)
        raise
    except Exception:
        session.rollback()
        _record_failure(
            session, identity, AppError(500, "admin_operation_failed", "管理操作未能完成")
        )
        raise
    else:
        try:
            session.add(AdminAuditEvent(**identity, result="success", changes_json=changes.values))
            session.commit()
        except Exception:
            session.rollback()
            error = AppError(
                503, "admin_audit_unavailable", "管理审计暂不可写，操作已回滚，请稍后重试"
            )
            _record_failure(session, identity, error)
            raise error from None
