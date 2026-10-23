# 用户体系红测试：/api/users/me 当前用户、资料修改与密码修改。

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.user import UserCredential, UserSession
from tests.auth_helpers import (
    DEFAULT_TEST_PASSWORD,
    SESSION_COOKIE,
    issue_session_token,
    login_as,
    make_account,
)

USER_READ_FIELDS = {
    "id",
    "display_name",
    "email",
    "avatar_url",
    "status",
    "deleted_at",
    "created_at",
    "updated_at",
    "role",
    "permissions",
}
NEW_PASSWORD = "Brand-New-Pass-2027"


def assert_error(response, *, status: int, code: str) -> dict:
    assert response.status_code == status, (
        f"期望 HTTP {status}/{code}，实际 {response.status_code}：{response.text}"
    )
    body = response.json()
    assert body.get("code") == code, f"错误码应为 {code}，实际响应：{body}"
    assert isinstance(body.get("detail"), str) and body["detail"]
    return body


# 验证 /users/me 返回原有公开字段并新增 role 与 permissions，不含任何认证秘密。
@pytest.mark.parametrize(
    ("role", "permissions"),
    [
        ("viewer", ["knowledge:read"]),
        ("member", ["knowledge:read", "knowledge:write"]),
        (
            "admin",
            [
                "audit:read",
                "knowledge:read",
                "knowledge:write",
                "models:manage",
                "operations:read",
                "users:manage",
            ],
        ),
    ],
)
def test_read_me_returns_public_fields_role_and_permissions(
    auth_client: TestClient, auth_db: Session, role: str, permissions: list[str]
) -> None:
    user = make_account(auth_db, email="alice@example.com", role=role, display_name="Alice")
    login_as(auth_client, auth_db, user)

    response = auth_client.get("/api/users/me")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == USER_READ_FIELDS
    assert body["id"] == str(user.id)
    assert body["email"] == "alice@example.com"
    assert body["role"] == role
    assert body["permissions"] == permissions
    assert body["deleted_at"] is None
    assert body["created_at"].endswith("Z")


# 验证角色变更后无需重新登录，下一次请求即返回最新角色与权限。
def test_read_me_reflects_role_change_without_relogin(
    auth_client: TestClient, auth_db: Session
) -> None:
    user = make_account(auth_db, role="member")
    login_as(auth_client, auth_db, user)

    user.role = "viewer"
    auth_db.add(user)
    auth_db.commit()

    assert auth_client.get("/api/users/me").json()["permissions"] == ["knowledge:read"]


# 验证修改显示名：去除首尾空白后保存，忽略 role/status/email 等越权字段。
def test_update_me_changes_display_name_only(auth_client: TestClient, auth_db: Session) -> None:
    user = make_account(auth_db, email="alice@example.com", role="viewer")
    login_as(auth_client, auth_db, user)

    response = auth_client.patch(
        "/api/users/me",
        json={
            "display_name": "  新名字  ",
            "role": "admin",
            "status": "disabled",
            "email": "evil@example.com",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["display_name"] == "新名字"
    assert body["role"] == "viewer"
    assert body["status"] == "active"
    assert body["email"] == "alice@example.com"
    auth_db.refresh(user)
    assert user.display_name == "新名字"
    assert user.role == "viewer"


# 验证非法显示名返回 422 invalid_display_name，原名称不变。
@pytest.mark.parametrize("display_name", ["", "   ", "名" * 101])
def test_update_me_rejects_invalid_display_name(
    auth_client: TestClient, auth_db: Session, display_name: str
) -> None:
    user = make_account(auth_db, display_name="原名")
    login_as(auth_client, auth_db, user)

    response = auth_client.patch("/api/users/me", json={"display_name": display_name})

    assert_error(response, status=422, code="invalid_display_name")
    auth_db.refresh(user)
    assert user.display_name == "原名"


# 验证匿名用户不能修改资料或密码。
def test_account_endpoints_require_login(auth_client: TestClient) -> None:
    assert_error(
        auth_client.patch("/api/users/me", json={"display_name": "x"}),
        status=401,
        code="auth_required",
    )
    assert_error(
        auth_client.post(
            "/api/users/me/password",
            json={"current_password": DEFAULT_TEST_PASSWORD, "new_password": NEW_PASSWORD},
        ),
        status=401,
        code="auth_required",
    )


# 验证改密成功：204、清除 Cookie、撤销该用户全部会话（含其他设备），旧密码失效、新密码可登录。
def test_change_password_revokes_all_sessions_and_requires_relogin(
    auth_client: TestClient, auth_db: Session
) -> None:
    user = make_account(auth_db, email="alice@example.com")
    other_device_token = issue_session_token(auth_db, user)
    current_token = login_as(auth_client, auth_db, user)
    old_hash = auth_db.exec(select(UserCredential)).one().password_hash

    response = auth_client.post(
        "/api/users/me/password",
        json={"current_password": DEFAULT_TEST_PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 204, response.text
    assert any(
        SESSION_COOKIE in value and "max-age=0" in value.lower()
        for value in response.headers.get_list("set-cookie")
    ), "改密后必须清除当前会话 Cookie"
    sessions = auth_db.exec(select(UserSession).where(UserSession.user_id == user.id)).all()
    for row in sessions:
        auth_db.refresh(row)
    assert sessions and all(row.revoked_at is not None for row in sessions)
    for token in (current_token, other_device_token):
        auth_client.cookies.set(SESSION_COOKIE, token)
        assert auth_client.get("/api/users/me").status_code == 401

    credential = auth_db.exec(select(UserCredential)).one()
    auth_db.refresh(credential)
    assert credential.password_hash != old_hash
    auth_client.cookies.clear()
    old_login = auth_client.post(
        "/api/auth/login", json={"email": "alice@example.com", "password": DEFAULT_TEST_PASSWORD}
    )
    assert old_login.status_code == 401
    new_login = auth_client.post(
        "/api/auth/login", json={"email": "alice@example.com", "password": NEW_PASSWORD}
    )
    assert new_login.status_code == 200, new_login.text


# 验证当前密码错误返回 400 current_password_incorrect（不是 401），会话保持有效、密码不变。
def test_change_password_with_wrong_current_password_keeps_session(
    auth_client: TestClient, auth_db: Session
) -> None:
    user = make_account(auth_db)
    login_as(auth_client, auth_db, user)
    old_hash = auth_db.exec(select(UserCredential)).one().password_hash

    response = auth_client.post(
        "/api/users/me/password",
        json={"current_password": "Wrong-Pass-2026", "new_password": NEW_PASSWORD},
    )

    assert_error(response, status=400, code="current_password_incorrect")
    assert auth_client.get("/api/users/me").status_code == 200
    credential = auth_db.exec(select(UserCredential)).one()
    auth_db.refresh(credential)
    assert credential.password_hash == old_hash


# 验证新密码不满足策略时返回 422 weak_password，且会话与密码都不变。
def test_change_password_rejects_weak_new_password(
    auth_client: TestClient, auth_db: Session
) -> None:
    user = make_account(auth_db, email="alice2026@example.com")
    login_as(auth_client, auth_db, user)

    response = auth_client.post(
        "/api/users/me/password",
        json={"current_password": DEFAULT_TEST_PASSWORD, "new_password": "alice2026"},
    )

    assert_error(response, status=422, code="weak_password")
    assert auth_client.get("/api/users/me").status_code == 200
