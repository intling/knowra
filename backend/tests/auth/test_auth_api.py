# 用户体系红测试：/api/auth 注册、登录、退出，会话 Cookie、限流、来源校验与秘密不外泄。
# 全部通过真实 Cookie 走认证链路，只覆盖数据库会话与限流器。

import logging
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.api.deps import get_login_rate_limiter
from app.core.config import get_settings
from app.main import app
from app.models.user import User, UserCredential, UserSession
from app.services.auth import LoginRateLimiter
from app.services.users import DEFAULT_USER_ID
from tests.auth_helpers import (
    DEFAULT_TEST_PASSWORD,
    SESSION_COOKIE,
    expire_all_sessions_of,
    login_as,
    make_account,
)

SECRET_FIELDS = {"password", "password_hash", "token", "token_hash", "session_token"}


def register(client: TestClient, **overrides) -> object:
    payload = {
        "display_name": "小明",
        "email": "xiaoming@example.com",
        "password": DEFAULT_TEST_PASSWORD,
    }
    payload.update(overrides)
    return client.post("/api/auth/register", json=payload)


def assert_error(response, *, status: int, code: str) -> dict:
    assert response.status_code == status, (
        f"期望 HTTP {status}/{code}，实际 {response.status_code}：{response.text}"
    )
    body = response.json()
    assert body.get("code") == code, f"错误码应为 {code}，实际响应：{body}"
    assert isinstance(body.get("detail"), str) and body["detail"], (
        f"错误响应必须包含可读中文原因：{body}"
    )
    return body


def session_cookie_header(response) -> str:
    headers = [
        value for value in response.headers.get_list("set-cookie") if SESSION_COOKIE in value
    ]
    assert headers, f"响应必须设置 {SESSION_COOKIE} Cookie，实际头：{response.headers}"
    return headers[-1]


# ── 注册 ─────────────────────────────────────────────────────────────────


# 验证注册成功：201、邮箱规范化、角色固定为 member、Cookie 属性安全且可直接访问 /users/me。
def test_register_creates_member_and_logs_in(auth_client: TestClient) -> None:
    response = register(auth_client, email="  Foo@Example.COM ")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "foo@example.com"
    assert body["display_name"] == "小明"
    assert body["role"] == "member"
    assert body["permissions"] == ["knowledge:read", "knowledge:write"]
    assert body["status"] == "active"
    assert SECRET_FIELDS.isdisjoint(body), f"注册响应不得包含认证秘密字段：{body}"

    cookie = session_cookie_header(response)
    lowered = cookie.lower()
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert "path=/api" in lowered
    assert "max-age=" in lowered

    me = auth_client.get("/api/users/me")
    assert me.status_code == 200, me.text
    assert me.json()["id"] == body["id"]


# 验证注册只保存 argon2id 哈希；新用户不是默认用户，也不继承其 UUID。
def test_register_persists_argon2_credential_and_new_uuid(
    auth_client: TestClient, auth_db: Session
) -> None:
    response = register(auth_client)
    user_id = response.json()["id"]

    credential = auth_db.exec(select(UserCredential)).one()
    assert str(credential.user_id) == user_id
    assert credential.password_hash.startswith("$argon2id$")
    assert DEFAULT_TEST_PASSWORD not in credential.password_hash
    assert user_id != str(DEFAULT_USER_ID)


# 验证公开注册不能通过请求体提升角色或注入权限。
def test_register_ignores_role_and_permission_fields(auth_client: TestClient) -> None:
    response = register(
        auth_client,
        role="admin",
        permissions=["users:manage"],
        status="disabled",
        id=str(DEFAULT_USER_ID),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["role"] == "member"
    assert "users:manage" not in body["permissions"]
    assert body["status"] == "active"
    assert body["id"] != str(DEFAULT_USER_ID)


# 验证第一个注册者即使系统中没有管理员，也只能是 member。
def test_first_registration_is_not_admin(auth_client: TestClient, auth_db: Session) -> None:
    assert auth_db.exec(select(User).where(User.role == "admin")).first() is None

    response = register(auth_client)

    assert response.json()["role"] == "member"


# 验证大小写/空白变体的重复邮箱返回 409 email_taken，且不新增账号。
def test_register_rejects_duplicate_email_case_insensitively(
    auth_client: TestClient, auth_db: Session
) -> None:
    make_account(auth_db, email="alice@example.com")

    response = register(auth_client, email=" ALICE@example.com")

    assert_error(response, status=409, code="email_taken")
    assert len(auth_db.exec(select(User)).all()) == 1
    assert SESSION_COOKIE not in response.headers.get("set-cookie", "")


# 验证非法注册输入返回对应 422 错误码，不创建账号或会话。
@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"email": "not-an-email"}, "invalid_email"),
        ({"display_name": "   "}, "invalid_display_name"),
        ({"password": "short1"}, "weak_password"),
        ({"password": "onlyletterspassword"}, "weak_password"),
        ({"email": "longpass2026@example.com", "password": "LongPass2026"}, "weak_password"),
    ],
)
def test_register_rejects_invalid_input(
    auth_client: TestClient, auth_db: Session, overrides: dict, code: str
) -> None:
    response = register(auth_client, **overrides)

    assert_error(response, status=422, code=code)
    assert auth_db.exec(select(User)).all() == []
    assert auth_db.exec(select(UserSession)).all() == []


# ── 登录 ─────────────────────────────────────────────────────────────────


# 验证登录成功：邮箱大小写不敏感，返回 UserRead 并签发可用会话。
def test_login_succeeds_with_case_insensitive_email(
    auth_client: TestClient, auth_db: Session
) -> None:
    user = make_account(auth_db, email="alice@example.com", role="viewer")

    response = auth_client.post(
        "/api/auth/login",
        json={"email": " ALICE@Example.com", "password": DEFAULT_TEST_PASSWORD},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(user.id)
    assert body["role"] == "viewer"
    assert body["permissions"] == ["knowledge:read"]
    assert SECRET_FIELDS.isdisjoint(body)
    session_cookie_header(response)
    assert auth_client.get("/api/users/me").status_code == 200


# 验证密码错误、邮箱不存在、账号无凭据（旧默认用户）返回完全相同的 401 响应。
def test_login_failures_do_not_reveal_account_existence(
    auth_client: TestClient, auth_db: Session
) -> None:
    make_account(auth_db, email="alice@example.com")
    auth_db.add(User(id=DEFAULT_USER_ID, display_name="Default User", email="legacy@example.com"))
    auth_db.commit()

    wrong_password = auth_client.post(
        "/api/auth/login", json={"email": "alice@example.com", "password": "Wrong-Pass-2026"}
    )
    unknown_email = auth_client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "Wrong-Pass-2026"}
    )
    no_credential = auth_client.post(
        "/api/auth/login", json={"email": "legacy@example.com", "password": "Wrong-Pass-2026"}
    )

    first = assert_error(wrong_password, status=401, code="invalid_credentials")
    assert unknown_email.json() == first
    assert no_credential.json() == first
    assert auth_db.exec(select(UserSession)).all() == []


# 验证已禁用账号输入正确密码返回 403 account_disabled，且不创建会话。
def test_login_rejects_disabled_account(auth_client: TestClient, auth_db: Session) -> None:
    make_account(auth_db, email="alice@example.com", status="disabled")

    response = auth_client.post(
        "/api/auth/login", json={"email": "alice@example.com", "password": DEFAULT_TEST_PASSWORD}
    )

    assert_error(response, status=403, code="account_disabled")
    assert auth_db.exec(select(UserSession)).all() == []


# 验证携带旧会话再次登录时，旧会话被撤销并签发新会话。
def test_login_rotates_existing_session(auth_client: TestClient, auth_db: Session) -> None:
    user = make_account(auth_db, email="alice@example.com")
    old_token = login_as(auth_client, auth_db, user)

    response = auth_client.post(
        "/api/auth/login", json={"email": "alice@example.com", "password": DEFAULT_TEST_PASSWORD}
    )

    assert response.status_code == 200, response.text
    old_row = auth_db.exec(
        select(UserSession).where(UserSession.token_hash == sha256(old_token.encode()).hexdigest())
    ).one()
    auth_db.refresh(old_row)
    assert old_row.revoked_at is not None, "再次登录必须撤销旧会话，防止会话固定"


# 验证同一邮箱连续失败 5 次后，即使密码正确也返回 429 和 Retry-After。
def test_login_is_rate_limited_after_repeated_failures(
    auth_client: TestClient, auth_db: Session
) -> None:
    make_account(auth_db, email="alice@example.com")

    for _ in range(5):
        failed = auth_client.post(
            "/api/auth/login", json={"email": "alice@example.com", "password": "Wrong-Pass-2026"}
        )
        assert failed.status_code == 401

    response = auth_client.post(
        "/api/auth/login", json={"email": "ALICE@example.com", "password": DEFAULT_TEST_PASSWORD}
    )

    assert_error(response, status=429, code="too_many_attempts")
    assert int(response.headers["Retry-After"]) > 0
    assert auth_db.exec(select(UserSession)).all() == []


# 验证窗口结束后恢复登录，且成功登录会清零失败计数。
def test_login_rate_limit_recovers_after_window_and_resets_on_success(
    auth_client: TestClient, auth_db: Session
) -> None:
    make_account(auth_db, email="alice@example.com")
    clock = {"now": 0.0}
    limiter = LoginRateLimiter(max_failures=3, window_seconds=60, clock=lambda: clock["now"])
    app.dependency_overrides[get_login_rate_limiter] = lambda: limiter
    bad = {"email": "alice@example.com", "password": "Wrong-Pass-2026"}
    good = {"email": "alice@example.com", "password": DEFAULT_TEST_PASSWORD}

    for _ in range(3):
        auth_client.post("/api/auth/login", json=bad)
    assert auth_client.post("/api/auth/login", json=good).status_code == 429

    clock["now"] = 61
    assert auth_client.post("/api/auth/login", json=good).status_code == 200

    for _ in range(2):
        auth_client.post("/api/auth/login", json=bad)
    assert auth_client.post("/api/auth/login", json=good).status_code == 200, (
        "成功登录后失败计数应清零，之前的失败不应继续累计"
    )


# ── 会话与退出 ───────────────────────────────────────────────────────────


# 验证退出：204、清除 Cookie、会话被撤销，旧 Cookie 再访问返回 401。
def test_logout_revokes_session_and_clears_cookie(
    auth_client: TestClient, auth_db: Session
) -> None:
    user = make_account(auth_db)
    token = login_as(auth_client, auth_db, user)

    response = auth_client.post("/api/auth/logout")

    assert response.status_code == 204, response.text
    cleared = session_cookie_header(response).lower()
    assert "max-age=0" in cleared or "expires=thu, 01 jan 1970" in cleared
    row = auth_db.exec(select(UserSession).where(UserSession.user_id == user.id)).one()
    auth_db.refresh(row)
    assert row.revoked_at is not None

    auth_client.cookies.set(SESSION_COOKIE, token)
    assert_error(auth_client.get("/api/users/me"), status=401, code="auth_required")


# 验证未登录调用退出也返回 204（幂等）。
def test_logout_without_session_is_idempotent(auth_client: TestClient) -> None:
    assert auth_client.post("/api/auth/logout").status_code == 204


# 验证匿名访问与伪造 Cookie 访问私有接口返回 401 auth_required 与重新登录提示。
def test_private_endpoint_requires_valid_session(auth_client: TestClient) -> None:
    anonymous = assert_error(auth_client.get("/api/users/me"), status=401, code="auth_required")
    assert "登录" in anonymous["detail"]

    auth_client.cookies.set(SESSION_COOKIE, "forged-token")
    forged = assert_error(auth_client.get("/api/users/me"), status=401, code="auth_required")
    assert "重新登录" in forged["detail"]


# 验证会话超过绝对有效期后返回 401。
def test_expired_session_returns_401(auth_client: TestClient, auth_db: Session) -> None:
    user = make_account(auth_db)
    login_as(auth_client, auth_db, user)
    expire_all_sessions_of(auth_db, user)

    assert_error(auth_client.get("/api/users/me"), status=401, code="auth_required")


# 验证默认用户存在且 active 时，匿名请求也不会回退为默认用户。
def test_default_user_is_not_used_as_fallback(auth_client: TestClient, auth_db: Session) -> None:
    auth_db.add(User(id=DEFAULT_USER_ID, display_name="Default User", status="active"))
    auth_db.commit()

    assert_error(auth_client.get("/api/users/me"), status=401, code="auth_required")


# ── CSRF 来源校验 ────────────────────────────────────────────────────────


# 验证不可信 Origin 的登录请求被 403 拒绝，且不会创建会话。
def test_untrusted_origin_is_rejected_for_login(auth_client: TestClient, auth_db: Session) -> None:
    make_account(auth_db, email="alice@example.com")

    response = auth_client.post(
        "/api/auth/login",
        json={"email": "alice@example.com", "password": DEFAULT_TEST_PASSWORD},
        headers={"Origin": "https://evil.example"},
    )

    assert_error(response, status=403, code="csrf_origin_rejected")
    assert auth_db.exec(select(UserSession)).all() == []


# 验证无 Origin 但 Sec-Fetch-Site 为 cross-site 的写请求同样被拒绝，且不修改资料。
def test_cross_site_fetch_metadata_is_rejected(auth_client: TestClient, auth_db: Session) -> None:
    user = make_account(auth_db, display_name="原名")
    login_as(auth_client, auth_db, user)

    response = auth_client.patch(
        "/api/users/me",
        json={"display_name": "被篡改"},
        headers={"Sec-Fetch-Site": "cross-site"},
    )

    assert_error(response, status=403, code="csrf_origin_rejected")
    auth_db.refresh(user)
    assert user.display_name == "原名"


# 验证白名单 Origin 正常放行。
def test_trusted_origin_is_allowed(auth_client: TestClient, auth_db: Session) -> None:
    make_account(auth_db, email="alice@example.com")
    trusted = get_settings().cors_origins[0]

    response = auth_client.post(
        "/api/auth/login",
        json={"email": "alice@example.com", "password": DEFAULT_TEST_PASSWORD},
        headers={"Origin": trusted, "Sec-Fetch-Site": "same-origin"},
    )

    assert response.status_code == 200, response.text


# ── 秘密不外泄 ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path", ["/api/auth/register", "/api/auth/login", "/api/users/me/password"]
)
@pytest.mark.parametrize("malformed_json", [False, True])
def test_validation_errors_do_not_echo_passwords(
    auth_client: TestClient, auth_db: Session, path: str, malformed_json: bool
) -> None:
    user = make_account(auth_db)
    login_as(auth_client, auth_db, user)
    secret = "Validation-Secret-2026"
    payload = {"password": {"secret": secret}, "current_password": {"secret": secret}}
    if malformed_json:
        response = auth_client.post(
            path,
            content='{"password":"' + secret + '",',
            headers={"Content-Type": "application/json"},
        )
    else:
        response = auth_client.post(path, json=payload)

    assert response.status_code == 422
    assert secret not in response.text
    errors = response.json()["detail"]
    assert errors and all({"loc", "msg", "type"} <= error.keys() for error in errors)
    assert all("input" not in error and "ctx" not in error for error in errors)


# 验证注册、登录、改密、退出全流程日志不包含明文密码、会话令牌或令牌哈希。
def test_auth_flow_logs_do_not_contain_secrets(
    auth_client: TestClient, auth_db: Session, caplog
) -> None:
    caplog.set_level(logging.DEBUG)
    new_password = "Brand-New-Pass-2027"

    registered = register(auth_client, email="secret@example.com")
    token = auth_client.cookies.get(SESSION_COOKIE)
    auth_client.post(
        "/api/auth/login", json={"email": "secret@example.com", "password": "Wrong-Pass-2026"}
    )
    auth_client.post(
        "/api/users/me/password",
        json={"current_password": DEFAULT_TEST_PASSWORD, "new_password": new_password},
    )
    auth_client.post(
        "/api/auth/login", json={"email": "secret@example.com", "password": new_password}
    )
    auth_client.post("/api/auth/logout")

    assert registered.status_code == 201
    assert token
    logged = "\n".join(record.getMessage() for record in caplog.records)
    for secret in (DEFAULT_TEST_PASSWORD, new_password, token, sha256(token.encode()).hexdigest()):
        assert secret not in logged, "认证日志泄露了密码、会话令牌或令牌哈希"
    assert any("user_id" in record.getMessage() for record in caplog.records), (
        "认证流程应输出带 user_id 的结构化日志，便于追溯"
    )
