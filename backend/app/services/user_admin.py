from uuid import UUID, uuid4

from sqlalchemy import or_, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, func, select

from app.core.errors import AppError
from app.core.logging import get_logger
from app.models.chat_quota import UserChatLimit
from app.models.user import User, UserCredential, UserSession, utc_now
from app.schemas.auth import (
    AdminUserCreate,
    AdminUserDetail,
    AdminUserUpdate,
    ChatLimitSnapshot,
    UserPage,
)
from app.schemas.user import UserRead
from app.services.admin_audit import admin_operation
from app.services.auth import revoke_user_sessions
from app.services.chat_quota import lock_account_quota, quota_snapshot
from app.services.passwords import (
    hash_password,
    normalize_display_name,
    normalize_email,
    validate_password,
)

logger = get_logger(__name__)


def list_users(
    session: Session,
    *,
    offset: int,
    limit: int,
    q: str | None = None,
    role: str | None = None,
    status: str | None = None,
) -> UserPage:
    filters = [User.deleted_at.is_(None)]
    if q and q.strip():
        literal = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append(
            or_(
                User.email.ilike(f"%{literal}%", escape="\\"),
                User.display_name.ilike(f"%{literal}%", escape="\\"),
            )
        )
    if role is not None:
        filters.append(User.role == role)
    if status is not None:
        filters.append(User.status == status)
    total = session.exec(select(func.count()).select_from(User).where(*filters)).one()
    users = session.exec(
        select(User).where(*filters).order_by(User.created_at, User.id).offset(offset).limit(limit)
    ).all()
    return UserPage(
        items=[UserRead.model_validate(user, from_attributes=True) for user in users],
        total=total,
        offset=offset,
        limit=limit,
    )


def read_target(session: Session, user_id: UUID) -> User:
    target = session.exec(select(User).where(User.id == user_id, User.deleted_at.is_(None))).first()
    if target is None:
        raise AppError(404, "user_not_found", "用户不存在")
    return target


def user_detail(session: Session, user_id: UUID) -> AdminUserDetail:
    target = read_target(session, user_id)
    count = session.exec(
        select(func.count())
        .select_from(UserSession)
        .where(
            UserSession.user_id == user_id,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > utc_now(),
        )
    ).one()
    return AdminUserDetail(
        user=UserRead.model_validate(target, from_attributes=True),
        active_session_count=count,
        chat_limit=quota_snapshot(session, user_id),
    )


def read_chat_limit(session: Session, user_id: UUID) -> ChatLimitSnapshot:
    read_target(session, user_id)
    return quota_snapshot(session, user_id)


def set_chat_limit(
    session: Session, actor: User, user_id: UUID, hourly_limit: int | None
) -> ChatLimitSnapshot:
    with admin_operation(session, actor, "user.chat_limit.update", user_id) as audit:
        lock_admins(session, actor)
        get_target(session, user_id)
        lock_account_quota(session, user_id)
        current = session.get(UserChatLimit, user_id, with_for_update=True, populate_existing=True)
        before = current.hourly_limit if current else None
        if hourly_limit is None:
            if current is not None:
                session.delete(current)
        else:
            current = current or UserChatLimit(user_id=user_id, hourly_limit=hourly_limit)
            current.hourly_limit = hourly_limit
            session.add(current)
        audit.capture({"hourly_limit": before}, {"hourly_limit": hourly_limit})
    return quota_snapshot(session, user_id)


def revoke_sessions(session: Session, actor: User, user_id: UUID) -> int:
    with admin_operation(session, actor, "user.sessions.revoke", user_id) as audit:
        lock_admins(session, actor)
        get_target(session, user_id)
        if user_id == actor.id:
            raise AppError(409, "cannot_revoke_self_sessions", "请在账户页面退出自己的登录设备")
        count = revoke_user_sessions(session, user_id, commit=False, only_active=True)
        audit.values["revoked_count"] = count
    return count


def lock_admins(session: Session, actor: User) -> list[User]:
    # 管理操作共用事务锁，串行化管理员存续检查，并重新核验在途请求操作者。
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(71022001)"))
    # Lock in deterministic order so simultaneous removals cannot both pass.
    admins = session.exec(
        select(User)
        .where(User.role == "admin", User.status == "active", User.deleted_at.is_(None))
        .order_by(User.id)
        # 不修改主键，使用 NO KEY UPDATE，允许向量任务外键取得 KEY SHARE，避免交叉锁死。
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    ).all()
    if not any(admin.id == actor.id for admin in admins):
        raise AppError(403, "forbidden", "当前账号已不具备用户管理权限")
    return admins


def get_target(session: Session, user_id: UUID) -> User:
    target = session.exec(
        select(User)
        .where(User.id == user_id, User.deleted_at.is_(None))
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    ).first()
    if target is None:
        raise AppError(404, "user_not_found", "用户不存在")
    return target


def update_user(session: Session, actor: User, user_id: UUID, payload: AdminUserUpdate) -> User:
    with admin_operation(session, actor, "user.update", user_id) as audit:
        changes = payload.model_dump(exclude_none=True)
        if not changes:
            raise AppError(422, "empty_update", "请至少提供角色或状态")
        admins = lock_admins(session, actor)
        target = get_target(session, user_id)
        if target.id == actor.id and changes.get("status") == "disabled":
            raise AppError(409, "cannot_disable_self", "不能禁用当前登录的账号")
        removing_admin = target in admins and (
            changes.get("role", target.role) != "admin"
            or changes.get("status", target.status) != "active"
        )
        if removing_admin and len(admins) <= 1:
            raise AppError(409, "last_admin", "系统必须保留至少一位有效管理员")
        before = {"role": target.role, "status": target.status}
        for key, value in changes.items():
            setattr(target, key, value)
        target.updated_at = utc_now()
        session.add(target)
        if changes.get("status") == "disabled":
            revoke_user_sessions(session, target.id, commit=False)
        audit.capture(before, {"role": target.role, "status": target.status})
    session.refresh(target)
    logger.info("管理员更新用户", user_id=str(target.id), actor_user_id=str(actor.id), **changes)
    return target


def create_user(session: Session, actor: User, payload: AdminUserCreate) -> User:
    target_id = uuid4()
    with admin_operation(session, actor, "user.create", target_id) as audit:
        email = normalize_email(payload.email)
        name = normalize_display_name(payload.display_name)
        validate_password(payload.password, email=email)
        lock_admins(session, actor)
        if session.exec(select(User).where(User.email == email)).first():
            raise AppError(409, "email_conflict", "该邮箱已被其他账号使用")
        target = User(
            id=target_id, email=email, display_name=name, role=payload.role, status=payload.status
        )
        session.add(target)
        try:
            session.flush()
            session.add(
                UserCredential(user_id=target.id, password_hash=hash_password(payload.password))
            )
            session.flush()
        except IntegrityError:
            raise AppError(409, "email_conflict", "该邮箱已被其他账号使用") from None
        audit.capture({}, {"role": target.role, "status": target.status})
    session.refresh(target)
    logger.info("管理员创建用户", user_id=str(target.id), actor_user_id=str(actor.id))
    return target


def reset_password(session: Session, actor: User, user_id: UUID, password: str) -> None:
    with admin_operation(session, actor, "user.reset_password", user_id):
        lock_admins(session, actor)
        target = get_target(session, user_id)
        if target.id == actor.id:
            raise AppError(409, "cannot_reset_self", "请在账户设置中验证当前密码并修改自己的密码")
        validate_password(password, email=target.email or "")
        credential = session.get(UserCredential, target.id)
        if credential is None:
            credential = UserCredential(user_id=target.id, password_hash=hash_password(password))
        else:
            credential.password_hash = hash_password(password)
            credential.updated_at = utc_now()
        session.add(credential)
        revoke_user_sessions(session, target.id, commit=False)
    logger.info("管理员重置密码", user_id=str(target.id), actor_user_id=str(actor.id))


def delete_user(session: Session, actor: User, user_id: UUID) -> None:
    with admin_operation(session, actor, "user.delete", user_id) as audit:
        admins = lock_admins(session, actor)
        target = get_target(session, user_id)
        if target.id == actor.id:
            raise AppError(409, "cannot_delete_self", "不能删除当前登录的账号")
        if target in admins and len(admins) <= 1:
            raise AppError(409, "last_admin", "系统必须保留至少一位有效管理员")
        before = {"status": target.status, "deleted": target.deleted_at is not None}
        target.deleted_at = target.updated_at = utc_now()
        target.status = "disabled"
        session.add(target)
        revoke_user_sessions(session, target.id, commit=False)
        audit.capture(before, {"status": target.status, "deleted": True})
    logger.info("管理员删除用户", user_id=str(target.id), actor_user_id=str(actor.id))
