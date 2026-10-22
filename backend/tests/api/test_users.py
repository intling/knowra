import logging
from collections.abc import Generator

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


# 测试默认用户存在且 active 时，匿名请求 /users/me 也必须返回 401，不再回退为默认用户。
def test_read_current_user_does_not_fall_back_to_default_user(
    users_client: TestClient, session: Session
) -> None:
    session.add(User(id=DEFAULT_USER_ID, display_name="Default User", status="active"))
    session.commit()

    response = users_client.get("/api/users/me")

    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "auth_required"
    assert "登录" in body["detail"]


# 测试用户管理接口不能被当作公开注册入口：POST /api/users 不存在。
def test_no_user_registration_endpoint_is_exposed(users_client: TestClient) -> None:
    response = users_client.post(
        "/api/users",
        json={
            "display_name": "Someone",
            "email": "someone@example.com",
        },
    )

    assert response.status_code in {401, 404, 405}


# =========================================================================
# 日志记录测试（spec: API 路由层日志记录 — 认证失败日志）
# =========================================================================


# 测试私有接口因缺少会话返回 401 时输出 INFO 日志，包含路径与原因，且不记录 Cookie 值。
def test_unauthenticated_request_logs_info_without_cookie_value(
    users_client: TestClient,
    caplog,
) -> None:
    caplog.set_level(logging.DEBUG)
    users_client.cookies.set("knowra_session", "forged-session-token-value")

    users_client.get("/api/users/me")

    auth_records = [
        r for r in caplog.records if r.levelname == "INFO" and "/api/users/me" in r.getMessage()
    ]
    assert auth_records, "401 前应输出包含请求路径的 INFO 日志"
    assert all("forged-session-token-value" not in r.getMessage() for r in caplog.records)
