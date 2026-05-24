from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db.session import get_session
from app.main import app
from app.models.user import User
from app.services.users import DEFAULT_USER_ID


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


@pytest.fixture
def users_client(session: Session) -> Generator[TestClient]:
    def override_get_session() -> Generator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_read_current_user_returns_default_user(users_client: TestClient, session: Session) -> None:
    created_at = datetime(2026, 5, 23, tzinfo=UTC)
    session.add(
        User(
            id=DEFAULT_USER_ID,
            display_name="Default User",
            status="active",
            created_at=created_at,
            updated_at=created_at,
        )
    )
    session.commit()

    response = users_client.get("/api/users/me")

    assert response.status_code == 200
    assert response.json() == {
        "id": str(DEFAULT_USER_ID),
        "display_name": "Default User",
        "email": None,
        "avatar_url": None,
        "status": "active",
        "deleted_at": None,
        "created_at": "2026-05-23T00:00:00Z",
        "updated_at": "2026-05-23T00:00:00Z",
    }


@pytest.mark.parametrize(
    ("status", "deleted_at"),
    [
        ("disabled", None),
        ("active", datetime(2026, 5, 23, tzinfo=UTC)),
    ],
)
def test_read_current_user_returns_error_when_default_user_is_unavailable(
    users_client: TestClient,
    session: Session,
    status: str,
    deleted_at: datetime | None,
) -> None:
    session.add(
        User(
            id=DEFAULT_USER_ID,
            display_name="Default User",
            status=status,
            deleted_at=deleted_at,
        )
    )
    session.commit()

    response = users_client.get("/api/users/me")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Current user is unavailable",
    }


def test_read_current_user_returns_error_when_default_user_is_missing(
    users_client: TestClient,
) -> None:
    response = users_client.get("/api/users/me")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Current user is unavailable",
    }


def test_no_user_registration_endpoint_is_exposed(users_client: TestClient) -> None:
    response = users_client.post(
        "/api/users",
        json={
            "display_name": "Someone",
            "email": "someone@example.com",
        },
    )

    assert response.status_code >= 400
