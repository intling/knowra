import logging
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.user import User
from app.services.users import (
    DEFAULT_USER_ID,
    CurrentUserUnavailableError,
    get_current_user,
)


@pytest.fixture
def session() -> Generator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as test_session:
        yield test_session


def test_get_current_user_returns_active_default_user(session: Session) -> None:
    session.add(
        User(
            id=DEFAULT_USER_ID,
            display_name="Default User",
            status="active",
        )
    )
    session.commit()

    user = get_current_user(session)

    assert user.id == DEFAULT_USER_ID
    assert user.display_name == "Default User"


def test_get_current_user_rejects_soft_deleted_default_user(session: Session) -> None:
    session.add(
        User(
            id=DEFAULT_USER_ID,
            display_name="Default User",
            status="active",
            deleted_at=datetime(2026, 5, 23, tzinfo=UTC),
        )
    )
    session.commit()

    with pytest.raises(CurrentUserUnavailableError):
        get_current_user(session)


def test_get_current_user_rejects_disabled_default_user(session: Session) -> None:
    session.add(
        User(
            id=DEFAULT_USER_ID,
            display_name="Default User",
            status="disabled",
        )
    )
    session.commit()

    with pytest.raises(CurrentUserUnavailableError):
        get_current_user(session)


# =========================================================================
# 日志记录测试（spec: Service 层日志记录 — users.py）
# RED 阶段：当前 users.py 未接入日志，以下测试预期全部失败。
# =========================================================================


# 测试查询到活跃默认用户时输出 DEBUG 级别日志，包含 user_id。
def test_get_current_user_logs_debug_on_success(
    session: Session,
    caplog,
) -> None:
    caplog.set_level(logging.DEBUG)
    session.add(
        User(
            id=DEFAULT_USER_ID,
            display_name="Default User",
            status="active",
        )
    )
    session.commit()

    get_current_user(session)

    user_records = [r for r in caplog.records if r.name == "app.services.users"]
    assert len(user_records) >= 1
    assert any(r.levelname == "DEBUG" for r in user_records)


# 测试未查到当前用户时输出 WARNING 级别日志，包含 default_user_id。
def test_get_current_user_logs_warning_on_not_found(
    session: Session,
    caplog,
) -> None:
    caplog.set_level(logging.DEBUG)

    with pytest.raises(CurrentUserUnavailableError):
        get_current_user(session)

    user_records = [r for r in caplog.records if r.name == "app.services.users"]
    assert len(user_records) >= 1
    assert any(r.levelname == "WARNING" for r in user_records)
