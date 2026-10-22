"""Short database transactions serialize admissions across application processes."""

from datetime import UTC, datetime, timedelta
from math import ceil
from uuid import UUID

from sqlalchemy import delete
from sqlmodel import Session, select

from app.core.errors import AppError
from app.models.chat_quota import ChatUsage, UserChatLimit
from app.models.user import utc_now

WINDOW = timedelta(hours=1)


def reserve_chat(session: Session, user_id: UUID, *, now: datetime | None = None) -> UUID | None:
    limit = session.get(UserChatLimit, user_id, with_for_update=True, populate_existing=True)
    if limit is None:
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
