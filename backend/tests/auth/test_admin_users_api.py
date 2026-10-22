# 用户体系红测试：/api/admin/users 管理员用户管理。
# 覆盖权限拒绝、分页、角色变更即时生效、禁用/启用与会话撤销、末位管理员与禁用自己保护。

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.models.user import UserSession
from tests.auth_helpers import (
    DEFAULT_TEST_PASSWORD,
    SESSION_COOKIE,
    issue_session_token,
    login_as,
    make_account,
)

SECRET_FIELDS = {"password", "password_hash", "token", "token_hash"}


def assert_error(response, *, status: int, code: str) -> dict:
    assert response.status_code == status, (
        f"期望 HTTP {status}/{code}，实际 {response.status_code}：{response.text}"
    )
    body = response.json()
    assert body.get("code") == code, f"错误码应为 {code}，实际响应：{body}"
    assert isinstance(body.get("detail"), str) and body["detail"]
    return body


@pytest.fixture
def admin(auth_db: Session):
    return make_account(auth_db, email="admin@example.com", role="admin", display_name="管理员")


# 验证 member 与 viewer 调用用户管理接口返回 403 forbidden，且不修改目标用户。
@pytest.mark.parametrize("role", ["member", "viewer"])
def test_non_admin_cannot_manage_users(
    auth_client: TestClient, auth_db: Session, admin, role: str
) -> None:
    actor = make_account(auth_db, role=role)
    target = make_account(auth_db, role="viewer")
    login_as(auth_client, auth_db, actor)

    listing = assert_error(auth_client.get("/api/admin/users"), status=403, code="forbidden")
    assert "权限" in listing["detail"]
    assert_error(
        auth_client.patch(f"/api/admin/users/{target.id}", json={"role": "admin"}),
        status=403,
        code="forbidden",
    )
    auth_db.refresh(target)
    assert target.role == "viewer"


# 验证匿名访问用户管理接口返回 401。
def test_anonymous_cannot_list_users(auth_client: TestClient) -> None:
    assert_error(auth_client.get("/api/admin/users"), status=401, code="auth_required")


# 验证分页列表：按创建时间升序、返回总数，排除软删除用户，不含认证秘密。
def test_admin_lists_users_with_pagination(auth_client: TestClient, auth_db: Session) -> None:
    base = datetime(2026, 10, 1, tzinfo=UTC)
    admin = make_account(auth_db, email="admin@example.com", role="admin", created_at=base)
    others = [
        make_account(auth_db, email=f"u{i}@example.com", created_at=base + timedelta(minutes=i))
        for i in range(1, 4)
    ]
    make_account(auth_db, email="gone@example.com", deleted=True, created_at=base)
    login_as(auth_client, auth_db, admin)

    response = auth_client.get("/api/admin/users", params={"offset": 1, "limit": 2})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 4
    assert body["offset"] == 1
    assert body["limit"] == 2
    assert [item["email"] for item in body["items"]] == [others[0].email, others[1].email]
    for item in body["items"]:
        assert SECRET_FIELDS.isdisjoint(item)
        assert {"role", "status", "permissions"} <= set(item)


# 验证分页参数越界返回 422（limit 必须在 1–100）。
@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_admin_list_validates_pagination(
    auth_client: TestClient, auth_db: Session, admin, params: dict
) -> None:
    login_as(auth_client, auth_db, admin)

    assert auth_client.get("/api/admin/users", params=params).status_code == 422


# 验证提升角色即时生效：被提升的成员无需重新登录即可访问管理接口。
def test_promote_member_takes_effect_immediately(
    auth_client: TestClient, auth_db: Session, admin
) -> None:
    member = make_account(auth_db, role="member")
    member_token = issue_session_token(auth_db, member)
    login_as(auth_client, auth_db, admin)

    response = auth_client.patch(f"/api/admin/users/{member.id}", json={"role": "admin"})

    assert response.status_code == 200, response.text
    assert response.json()["role"] == "admin"
    assert "users:manage" in response.json()["permissions"]
    auth_client.cookies.set(SESSION_COOKIE, member_token)
    assert auth_client.get("/api/admin/users").status_code == 200


# 验证降级为 viewer 后，目标用户下一次写请求即被拒绝。
def test_demote_to_viewer_revokes_write_permission(
    auth_client: TestClient, auth_db: Session, admin
) -> None:
    member = make_account(auth_db, role="member")
    member_token = issue_session_token(auth_db, member)
    login_as(auth_client, auth_db, admin)

    auth_client.patch(f"/api/admin/users/{member.id}", json={"role": "viewer"})

    auth_client.cookies.set(SESSION_COOKIE, member_token)
    upload = auth_client.post("/api/uploads", files={"file": ("notes.txt", b"notes", "text/plain")})
    assert_error(upload, status=403, code="forbidden")


# 验证禁用用户：撤销其全部会话，旧会话立即 401，再登录返回 403；资料归属不受影响。
def test_disable_user_revokes_sessions_and_blocks_login(
    auth_client: TestClient, auth_db: Session, admin
) -> None:
    member = make_account(auth_db, email="member@example.com")
    member_token = issue_session_token(auth_db, member)
    login_as(auth_client, auth_db, admin)

    response = auth_client.patch(f"/api/admin/users/{member.id}", json={"status": "disabled"})

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "disabled"
    rows = auth_db.exec(select(UserSession).where(UserSession.user_id == member.id)).all()
    for row in rows:
        auth_db.refresh(row)
    assert rows and all(row.revoked_at is not None for row in rows)

    auth_client.cookies.set(SESSION_COOKIE, member_token)
    assert_error(auth_client.get("/api/users/me"), status=401, code="auth_required")
    auth_client.cookies.clear()
    login = auth_client.post(
        "/api/auth/login", json={"email": "member@example.com", "password": DEFAULT_TEST_PASSWORD}
    )
    assert_error(login, status=403, code="account_disabled")


# 验证重新启用后可再次登录，但禁用前的旧会话不会恢复。
def test_reenable_user_allows_login_but_not_old_sessions(
    auth_client: TestClient, auth_db: Session, admin
) -> None:
    member = make_account(auth_db, email="member@example.com")
    member_token = issue_session_token(auth_db, member)
    login_as(auth_client, auth_db, admin)
    auth_client.patch(f"/api/admin/users/{member.id}", json={"status": "disabled"})

    response = auth_client.patch(f"/api/admin/users/{member.id}", json={"status": "active"})

    assert response.status_code == 200, response.text
    auth_client.cookies.set(SESSION_COOKIE, member_token)
    assert auth_client.get("/api/users/me").status_code == 401
    auth_client.cookies.clear()
    login = auth_client.post(
        "/api/auth/login", json={"email": "member@example.com", "password": DEFAULT_TEST_PASSWORD}
    )
    assert login.status_code == 200, login.text


# 验证唯一有效管理员不能把自己降级，返回 409 last_admin 且角色不变。
def test_last_admin_cannot_demote_self(auth_client: TestClient, auth_db: Session, admin) -> None:
    make_account(auth_db, role="admin", status="disabled")
    make_account(auth_db, role="admin", deleted=True)
    login_as(auth_client, auth_db, admin)

    response = auth_client.patch(f"/api/admin/users/{admin.id}", json={"role": "member"})

    body = assert_error(response, status=409, code="last_admin")
    assert "管理员" in body["detail"]
    auth_db.refresh(admin)
    assert admin.role == "admin"


# 验证存在其他有效管理员时，管理员可以自降级。
def test_admin_can_demote_self_when_another_admin_exists(
    auth_client: TestClient, auth_db: Session, admin
) -> None:
    make_account(auth_db, role="admin")
    login_as(auth_client, auth_db, admin)

    response = auth_client.patch(f"/api/admin/users/{admin.id}", json={"role": "member"})

    assert response.status_code == 200, response.text
    assert response.json()["role"] == "member"
    assert_error(auth_client.get("/api/admin/users"), status=403, code="forbidden")


# 验证降级另一位管理员导致没有有效管理员时同样被拒绝（另一管理员已被禁用的场景）。
def test_cannot_remove_last_active_admin_via_other_account(
    auth_client: TestClient, auth_db: Session, admin
) -> None:
    second_admin = make_account(auth_db, role="admin")
    login_as(auth_client, auth_db, admin)
    assert (
        auth_client.patch(
            f"/api/admin/users/{second_admin.id}", json={"status": "disabled"}
        ).status_code
        == 200
    )

    response = auth_client.patch(f"/api/admin/users/{admin.id}", json={"role": "viewer"})

    assert_error(response, status=409, code="last_admin")


# 验证管理员不能禁用自己，返回 409 cannot_disable_self 且状态不变。
def test_admin_cannot_disable_self(auth_client: TestClient, auth_db: Session, admin) -> None:
    make_account(auth_db, role="admin")
    login_as(auth_client, auth_db, admin)

    response = auth_client.patch(f"/api/admin/users/{admin.id}", json={"status": "disabled"})

    assert_error(response, status=409, code="cannot_disable_self")
    auth_db.refresh(admin)
    assert admin.status == "active"


# 验证目标用户不存在或已软删除时返回 404 user_not_found。
def test_update_missing_or_deleted_user_returns_404(
    auth_client: TestClient, auth_db: Session, admin
) -> None:
    deleted = make_account(auth_db, deleted=True)
    login_as(auth_client, auth_db, admin)

    for target_id in (uuid4(), deleted.id):
        response = auth_client.patch(f"/api/admin/users/{target_id}", json={"role": "viewer"})
        assert_error(response, status=404, code="user_not_found")


# 验证空更新返回 422 empty_update；非法角色或状态值返回 422。
@pytest.mark.parametrize(
    ("payload", "code"),
    [({}, "empty_update"), ({"role": "root"}, None), ({"status": "banned"}, None)],
)
def test_update_user_validates_payload(
    auth_client: TestClient, auth_db: Session, admin, payload: dict, code: str | None
) -> None:
    member = make_account(auth_db)
    login_as(auth_client, auth_db, admin)

    response = auth_client.patch(f"/api/admin/users/{member.id}", json=payload)

    assert response.status_code == 422, response.text
    if code is not None:
        assert response.json()["code"] == code
    auth_db.refresh(member)
    assert (member.role, member.status) == ("member", "active")


# 验证管理员没有越权读取他人资料的能力：用户管理权限不扩展资料可见范围。
def test_admin_cannot_read_other_users_documents(
    auth_client: TestClient, auth_db: Session, admin, tmp_path
) -> None:
    from tests.auth_helpers import seed_knowledge_chain

    owner = make_account(auth_db)
    _upload, parsed, _job, chunks, _embeddings = seed_knowledge_chain(
        auth_db, tmp_path / "uploads", owner
    )
    login_as(auth_client, auth_db, admin)

    assert auth_client.get("/api/parsed-documents").json() == []
    assert auth_client.get(f"/api/parsed-documents/{parsed.id}/segments").status_code == 404
    assert auth_client.get(f"/api/document-chunks/{chunks[0].id}").status_code == 404
