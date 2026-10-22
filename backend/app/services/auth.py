import math
import secrets
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import Lock
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.errors import AppError
from app.core.logging import get_logger
from app.models.user import User, UserCredential, UserSession, utc_now
from app.services.passwords import (
    DUMMY_HASH,
    hash_password,
    needs_rehash,
    normalize_display_name,
    normalize_email,
    validate_password,
    verify_password,
)

logger = get_logger(__name__)
SESSION_COOKIE = "knowra_session"


class LoginRateLimiter:
    def __init__(
        self,
        *,
        max_failures: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.clock = clock
        self._failures: dict[str, deque[float]] = {}
        self._lock = Lock()

    def _prune(self, email: str) -> deque[float]:
        failures = self._failures.get(email, deque())
        cutoff = self.clock() - self.window_seconds
        while failures and failures[0] <= cutoff:
            failures.popleft()
        if not failures:
            self._failures.pop(email, None)
        return failures

    def retry_after(self, email: str) -> int | None:
        with self._lock:
            failures = self._prune(email)
            if len(failures) < self.max_failures:
                return None
            return max(1, math.ceil(failures[0] + self.window_seconds - self.clock()))

    def record_failure(self, email: str) -> None:
        with self._lock:
            failures = self._prune(email)
            failures.append(self.clock())
            self._failures[email] = failures

    def reset(self, email: str) -> None:
        with self._lock:
            self._failures.pop(email, None)


def create_session(session: Session, user: User, *, ttl: timedelta) -> str:
    token = secrets.token_urlsafe(32)
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=sha256(token.encode()).hexdigest(),
            expires_at=utc_now() + ttl,
        )
    )
    session.commit()
    return token


def resolve_session_user(session: Session, token: str | None) -> User | None:
    if not token:
        return None
    return session.exec(
        select(User)
        .join(UserSession, UserSession.user_id == User.id)
        .where(
            UserSession.token_hash == sha256(token.encode()).hexdigest(),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > datetime.now(UTC),
            User.status == "active",
            User.deleted_at.is_(None),
        )
        .execution_options(populate_existing=True)
    ).first()


def revoke_session(session: Session, token: str | None, *, commit: bool = True) -> None:
    if not token:
        return
    row = session.exec(
        select(UserSession).where(UserSession.token_hash == sha256(token.encode()).hexdigest())
    ).first()
    if row is not None and row.revoked_at is None:
        row.revoked_at = utc_now()
        session.add(row)
        if commit:
            session.commit()
        logger.info("会话已撤销", user_id=str(row.user_id), reason="logout_or_rotation")


def revoke_user_sessions(session: Session, user_id: UUID, *, commit: bool = True) -> int:
    rows = session.exec(
        select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    ).all()
    for row in rows:
        row.revoked_at = utc_now()
        session.add(row)
    if commit:
        session.commit()
    return len(rows)


def register_user(session: Session, *, email: str, display_name: str, password: str) -> User:
    email = normalize_email(email)
    display_name = normalize_display_name(display_name)
    validate_password(password, email=email)
    if session.exec(select(User).where(User.email == email)).first():
        raise AppError(409, "email_taken", "此邮箱已注册")
    user = User(email=email, display_name=display_name)
    session.add(user)
    session.add(UserCredential(user_id=user.id, password_hash=hash_password(password)))
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise AppError(409, "email_taken", "此邮箱已注册") from exc
    session.refresh(user)
    logger.info("用户注册成功", user_id=str(user.id))
    return user


def authenticate_user(
    session: Session, *, email: str, password: str, limiter: LoginRateLimiter
) -> User:
    # Invalid email syntax also receives the generic credential error.
    email = email.strip().lower()
    retry_after = limiter.retry_after(email)
    if retry_after is not None:
        raise AppError(
            429,
            "too_many_attempts",
            "登录尝试过多，请稍后重试",
            headers={"Retry-After": str(retry_after)},
        )
    user = session.exec(select(User).where(User.email == email, User.deleted_at.is_(None))).first()
    credential = session.get(UserCredential, user.id) if user else None
    valid = verify_password(credential.password_hash if credential else DUMMY_HASH, password)
    if not valid or credential is None:
        limiter.record_failure(email)
        logger.warning(
            "用户登录失败",
            reason="invalid_credentials",
            **({"user_id": str(user.id)} if user else {}),
        )
        raise AppError(401, "invalid_credentials", "邮箱或密码错误")
    if user.status != "active":
        logger.warning("用户登录失败", user_id=str(user.id), reason="account_disabled")
        raise AppError(403, "account_disabled", "账号已被禁用，请联系管理员")
    if needs_rehash(credential.password_hash):
        credential.password_hash = hash_password(password)
        credential.updated_at = utc_now()
        session.add(credential)
        session.commit()
    limiter.reset(email)
    logger.info("用户登录成功", user_id=str(user.id))
    return user


def update_profile(session: Session, user: User, display_name: str) -> User:
    user.display_name = normalize_display_name(display_name)
    user.updated_at = utc_now()
    session.add(user)
    session.commit()
    session.refresh(user)
    logger.info("用户资料已更新", user_id=str(user.id))
    return user


def change_password(
    session: Session, user: User, *, current_password: str, new_password: str
) -> None:
    credential = session.get(UserCredential, user.id)
    if credential is None or not verify_password(credential.password_hash, current_password):
        raise AppError(400, "current_password_incorrect", "当前密码错误")
    validate_password(new_password, email=user.email or "")
    credential.password_hash = hash_password(new_password)
    credential.updated_at = utc_now()
    session.add(credential)
    revoke_user_sessions(session, user.id, commit=False)
    session.commit()
    logger.info("用户密码已修改", user_id=str(user.id), reason="all_sessions_revoked")
