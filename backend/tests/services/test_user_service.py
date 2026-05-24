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
