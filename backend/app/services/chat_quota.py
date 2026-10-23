"""Short database transactions serialize admissions across application processes."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from math import ceil
from uuid import UUID

from sqlalchemy import delete, text
from sqlmodel import Session, func, select

from app.core.errors import AppError
from app.models.chat_quota import ChatUsage, UserChatLimit
from app.models.user import utc_now
from app.schemas.auth import ChatLimitSnapshot

WINDOW = timedelta(hours=1)


def lock_account_quota(session: Session, user_id: UUID) -> None:
    # 使用独立命名空间的稳定 64 位散列，覆盖尚无额度行的账号；不使用进程随机 hash。
    if session.get_bind().dialect.name == "postgresql":
        key = int.from_bytes(sha256(b"knowra:quota:" + user_id.bytes).digest()[:8], signed=True)
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def quota_snapshot(session: Session, user_id: UUID) -> ChatLimitSnapshot:
    timestamp = utc_now()
    limit = session.get(UserChatLimit, user_id, populate_existing=True)
    occupied = None
    if limit is not None:
        occupied = session.exec(
            select(func.count())
            .select_from(ChatUsage)
            .where(ChatUsage.user_id == user_id, ChatUsage.created_at > timestamp - WINDOW)
        ).one()
    return ChatLimitSnapshot(
        hourly_limit=limit.hourly_limit if limit else None,
        occupied_slots=occupied,
        remaining=max(0, limit.hourly_limit - occupied) if limit else None,
        observed_at=timestamp,
    )


def reserve_chat(session: Session, user_id: UUID, *, now: datetime | None = None) -> UUID | None:
    lock_account_quota(session, user_id)
    limit = session.get(UserChatLimit, user_id, with_for_update=True, populate_existing=True)
    if limit is None:
        session.commit()
        return None
    timestamp = now or utc_now()
    cutoff = timestamp - WINDOW
    session.execute(
        delete(ChatUsage).where(ChatUsage.user_id == user_id, ChatUsage.created_at <= cutoff)
    )
    recent = session.exec(
        select(ChatUsage)
        .where(ChatUsage.user_id == user_id, ChatUsage.created_at > cutoff)
        .order_by(ChatUsage.created_at)
    ).all()
    if len(recent) >= limit.hourly_limit:
        hourly_limit = limit.hourly_limit
        oldest = recent[0].created_at
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=UTC)
        retry_after = max(1, ceil((oldest + WINDOW - timestamp).total_seconds()))
        session.rollback()
        raise AppError(
            429,
            "chat_quota_exceeded",
            f"该账号最近 60 分钟最多成功问答 {hourly_limit} 次，"
            f"额度已用完，请稍后重试（约 {retry_after} 秒）。",
            headers={"Retry-After": str(retry_after)},
        )
    usage = ChatUsage(user_id=user_id, created_at=timestamp)
    reservation_id = usage.id
    session.add(usage)
    session.commit()
    return reservation_id


def release_chat(session: Session, reservation_id: UUID | None) -> None:
    if reservation_id is None:
        return
    session.rollback()
    session.execute(delete(ChatUsage).where(ChatUsage.id == reservation_id))
    session.commit()
