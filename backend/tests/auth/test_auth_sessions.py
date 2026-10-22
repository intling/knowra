# 用户体系红测试：服务端会话服务。
# 验证令牌只以 SHA-256 哈希落库、按绝对过期/撤销/用户状态判定有效性，以及按用户批量撤销。

from datetime import UTC, datetime, timedelta
from hashlib import sha256

from sqlmodel import Session, select

from app.models.user import UserSession
from app.services.auth import (
    create_session,
    resolve_session_user,
    revoke_session,
    revoke_user_sessions,
)
from app.services.users import DEFAULT_USER_ID
from tests.auth_helpers import expire_all_sessions_of, make_account


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


# 验证创建会话只保存令牌哈希：原始令牌不出现在任何列，过期时间按 TTL 计算。
def test_create_session_stores_only_token_hash(auth_db: Session) -> None:
    user = make_account(auth_db)

    before = datetime.now(UTC)
    token = create_session(auth_db, user, ttl=timedelta(hours=2))

    rows = auth_db.exec(select(UserSession).where(UserSession.user_id == user.id)).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.token_hash == sha256(token.encode()).hexdigest()
    assert token not in {str(value) for value in row.model_dump().values()}, (
        "数据库会话行不得保存原始令牌"
    )
    assert row.revoked_at is None
    expires_at = _as_utc(row.expires_at)
    assert before + timedelta(hours=2) - timedelta(seconds=5) <= expires_at
    assert expires_at <= datetime.now(UTC) + timedelta(hours=2)
    assert len(token) >= 40, "会话令牌必须具备足够熵（token_urlsafe(32)）"


# 验证有效令牌解析出会话用户；空令牌、伪造令牌都返回 None。
def test_resolve_session_user_returns_owner_or_none(auth_db: Session) -> None:
    user = make_account(auth_db)
    token = create_session(auth_db, user, ttl=timedelta(hours=1))

    resolved = resolve_session_user(auth_db, token)

    assert resolved is not None
    assert resolved.id == user.id
    assert resolve_session_user(auth_db, None) is None
    assert resolve_session_user(auth_db, "") is None
    assert resolve_session_user(auth_db, token + "x") is None


# 验证超过绝对有效期的会话失效。
def test_resolve_session_user_rejects_expired_session(auth_db: Session) -> None:
    user = make_account(auth_db)
    token = create_session(auth_db, user, ttl=timedelta(hours=1))
    expire_all_sessions_of(auth_db, user)

    assert resolve_session_user(auth_db, token) is None


# 验证撤销后的会话失效，且 revoked_at 被写入。
def test_revoke_session_marks_revoked_and_invalidates(auth_db: Session) -> None:
    user = make_account(auth_db)
    token = create_session(auth_db, user, ttl=timedelta(hours=1))

    revoke_session(auth_db, token)

    row = auth_db.exec(select(UserSession).where(UserSession.user_id == user.id)).one()
    assert row.revoked_at is not None
    assert resolve_session_user(auth_db, token) is None


# 验证撤销不存在或空的令牌不会报错（退出接口需要幂等）。
def test_revoke_session_ignores_unknown_token(auth_db: Session) -> None:
    revoke_session(auth_db, None)
    revoke_session(auth_db, "unknown-token")


# 验证会话关联用户被禁用或软删除后，会话立即失效。
def test_resolve_session_user_rejects_disabled_or_deleted_user(auth_db: Session) -> None:
    disabled = make_account(auth_db)
    deleted = make_account(auth_db)
    disabled_token = create_session(auth_db, disabled, ttl=timedelta(hours=1))
    deleted_token = create_session(auth_db, deleted, ttl=timedelta(hours=1))

    disabled.status = "disabled"
    deleted.deleted_at = datetime.now(UTC)
    auth_db.add(disabled)
    auth_db.add(deleted)
    auth_db.commit()

    assert resolve_session_user(auth_db, disabled_token) is None
    assert resolve_session_user(auth_db, deleted_token) is None


# 验证按用户批量撤销只影响目标用户的有效会话，返回撤销数量。
def test_revoke_user_sessions_only_affects_target_user(auth_db: Session) -> None:
    target = make_account(auth_db)
    other = make_account(auth_db)
    target_tokens = [create_session(auth_db, target, ttl=timedelta(hours=1)) for _ in range(2)]
    other_token = create_session(auth_db, other, ttl=timedelta(hours=1))

    revoked = revoke_user_sessions(auth_db, target.id)

    assert revoked == 2
    assert all(resolve_session_user(auth_db, token) is None for token in target_tokens)
    assert resolve_session_user(auth_db, other_token) is not None


# 验证默认用户即使存在且 active，也不能在没有会话时被解析为当前用户。
def test_default_user_is_never_resolved_without_session(auth_db: Session) -> None:
    from app.models.user import User

    auth_db.add(User(id=DEFAULT_USER_ID, display_name="Default User", status="active"))
    auth_db.commit()

    assert resolve_session_user(auth_db, None) is None
    assert resolve_session_user(auth_db, "guessed-token") is None
