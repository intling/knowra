"""用户管理增量 RED：建号、重置密码、软删除及权限边界。"""

from uuid import UUID, uuid4

import pytest
from sqlmodel import select

from app.models.user import User, UserCredential, UserSession
from tests.admin_console.helpers import assert_error, assert_status
from tests.auth_helpers import (
    DEFAULT_TEST_PASSWORD,
    SESSION_COOKIE,
    issue_session_token,
    login_as,
    make_account,
    seed_knowledge_chain,
)

NEW_PASSWORD = "Reset-Knowra-2026"
CREATE = {
    "email": "new-user@example.com",
    "display_name": "新用户",
    "password": DEFAULT_TEST_PASSWORD,
    "role": "member",
}


# 验证管理员可创建三类角色，新账号可登录，创建过程不切换管理员会话。
@pytest.mark.parametrize("role", ["admin", "member", "viewer"])
def test_create_account_and_login(auth_client, auth_db, admin_actor, role):
    body = assert_status(
        auth_client.post("/api/admin/users", json=CREATE | {"role": role}),
        201,
        f"管理员创建 {role} 账号应成功，现有列表接口不足以支持建号",
    )
    assert body["role"] == role
    assert {"password", "password_hash", "token", "token_hash"}.isdisjoint(body)
    credential = auth_db.get(UserCredential, UUID(body["id"]))
    assert credential is not None and credential.password_hash != DEFAULT_TEST_PASSWORD
    me = assert_status(auth_client.get("/api/users/me"), 200, "建号不得替换操作者会话")
    assert me["id"] == str(admin_actor.id)
    auth_client.cookies.clear()
    logged_in = assert_status(
        auth_client.post(
            "/api/auth/login",
            json={"email": CREATE["email"], "password": DEFAULT_TEST_PASSWORD},
        ),
        200,
        "管理员创建的启用账号必须能用初始密码登录",
    )
    assert logged_in["id"] == body["id"]


# 验证省略角色时默认成员，邮箱和名称统一规范化。
def test_create_normalizes_identity_and_defaults_to_member(auth_client, auth_db, admin_actor):
    payload = CREATE | {"email": " New-User@Example.COM ", "display_name": " 新用户 "}
    payload.pop("role")
    body = assert_status(auth_client.post("/api/admin/users", json=payload), 201, "建号规范化")
    assert (body["email"], body["display_name"], body["role"], body["status"]) == (
        "new-user@example.com",
        "新用户",
        "member",
        "active",
    )


# 验证启用与禁用建号状态可控，禁用账号不能登录。
def test_create_disabled_account_blocks_login(auth_client, admin_actor):
    body = assert_status(
        auth_client.post("/api/admin/users", json=CREATE | {"status": "disabled"}),
        201,
        "管理员可预建禁用账号",
    )
    assert body["status"] == "disabled"
    auth_client.cookies.clear()
    assert_error(
        auth_client.post(
            "/api/auth/login", json={"email": CREATE["email"], "password": DEFAULT_TEST_PASSWORD}
        ),
        403,
        "account_disabled",
        "禁用账号不能使用初始密码登录",
    )


# 验证错误输入不会创建用户或泄露密码，角色只能使用既有固定枚举。
@pytest.mark.parametrize(
    "changes",
    [
        {"email": "invalid"},
        {"display_name": " "},
        {"display_name": "名" * 101},
        {"password": "short"},
        {"password": "onlyletterslong"},
        {"role": "root"},
        {"status": "banned"},
    ],
)
def test_create_validates_without_partial_writes(auth_client, auth_db, admin_actor, changes):
    before = len(auth_db.exec(select(User)).all())
    payload = CREATE | changes
    response = auth_client.post("/api/admin/users", json=payload)
    body = assert_status(response, 422, f"建号字段无效 {list(changes)} 应拒绝且不给出秘密")
    assert body.get("detail"), f"字段错误必须说明原因：{body}"
    assert payload["password"] not in response.text
    assert len(auth_db.exec(select(User)).all()) == before


# 验证重复邮箱（含软删除账号）返回明确冲突，不能覆盖账号凭据或认领历史资料。
@pytest.mark.parametrize("deleted", [False, True])
def test_create_rejects_duplicate_normalized_email(auth_client, auth_db, admin_actor, deleted):
    target = make_account(auth_db, email=CREATE["email"], deleted=deleted)
    before = auth_db.get(UserCredential, target.id).password_hash
    assert_error(
        auth_client.post("/api/admin/users", json=CREATE | {"email": "NEW-USER@example.com"}),
        409,
        "email_conflict",
        "规范化后重复的邮箱应保留原账号归属",
    )
    auth_db.expire_all()
    assert auth_db.get(UserCredential, target.id).password_hash == before


# 验证重置他人密码撤销全部会话，旧密码失效，新密码可登录，操作者会话仍有效。
def test_reset_password_revokes_all_target_sessions(auth_client, auth_db, admin_actor):
    target = make_account(auth_db)
    tokens = [issue_session_token(auth_db, target) for _ in range(2)]
    response = auth_client.post(
        f"/api/admin/users/{target.id}/reset-password", json={"new_password": NEW_PASSWORD}
    )
    assert_status(response, 204, "管理员重置他人密码后必须撤销其全部设备会话")
    assert response.content == b""
    assert_status(auth_client.get("/api/users/me"), 200, "重置他人密码不影响管理员会话")
    auth_db.expire_all()
    sessions = auth_db.exec(select(UserSession).where(UserSession.user_id == target.id)).all()
    assert len(sessions) == 2 and all(item.revoked_at is not None for item in sessions)
    for token in tokens:
        auth_client.cookies.set(SESSION_COOKIE, token)
        assert_error(auth_client.get("/api/users/me"), 401, "auth_required", "重置后旧会话失效")
    auth_client.cookies.clear()
    assert_error(
        auth_client.post(
            "/api/auth/login", json={"email": target.email, "password": DEFAULT_TEST_PASSWORD}
        ),
        401,
        "invalid_credentials",
        "重置后旧密码应失效",
    )
    assert_status(
        auth_client.post("/api/auth/login", json={"email": target.email, "password": NEW_PASSWORD}),
        200,
        "重置后启用用户可使用新密码登录",
    )


# 验证重置禁用账号密码不会顺带启用账号。
def test_reset_disabled_user_preserves_disabled_status(auth_client, auth_db, admin_actor):
    target = make_account(auth_db, status="disabled")
    assert_status(
        auth_client.post(
            f"/api/admin/users/{target.id}/reset-password", json={"new_password": NEW_PASSWORD}
        ),
        204,
        "管理员可重置禁用账号密码但不得启用账号",
    )
    auth_db.refresh(target)
    assert target.status == "disabled"


# 验证弱密码重置失败时，原密码哈希和目标会话均保持不变。
def test_weak_reset_keeps_password_and_sessions(auth_client, auth_db, admin_actor):
    target = make_account(auth_db)
    token = issue_session_token(auth_db, target)
    original = auth_db.get(UserCredential, target.id).password_hash
    response = auth_client.post(
        f"/api/admin/users/{target.id}/reset-password", json={"new_password": "short"}
    )
    assert_error(response, 422, "weak_password", "重置弱密码必须拒绝且保持旧凭据有效")
    auth_db.expire_all()
    assert auth_db.get(UserCredential, target.id).password_hash == original
    auth_client.cookies.set(SESSION_COOKIE, token)
    assert_status(auth_client.get("/api/users/me"), 200, "失败重置不能撤销目标会话")


# 验证管理员删除自己和重置自己均被明确拒绝，并保持当前会话和账号状态。
@pytest.mark.parametrize(
    "operation,code", [("delete", "cannot_delete_self"), ("reset-password", "cannot_reset_self")]
)
def test_self_management_uses_account_settings(auth_client, auth_db, admin_actor, operation, code):
    make_account(auth_db, role="admin")
    response = (
        auth_client.delete(f"/api/admin/users/{admin_actor.id}")
        if operation == "delete"
        else auth_client.post(
            f"/api/admin/users/{admin_actor.id}/reset-password", json={"new_password": NEW_PASSWORD}
        )
    )
    assert_error(response, 409, code, "后台不得删除当前账号或旁路自身账户改密验证")
    assert_status(auth_client.get("/api/users/me"), 200, "自身保护失败后会话仍有效")


# 验证删除使账号和会话失效，但完整私有资料链及外键保留且管理员仍不可读。
def test_delete_preserves_private_knowledge(auth_client, auth_db, admin_actor, tmp_path):
    target = make_account(auth_db)
    token = issue_session_token(auth_db, target)
    resources = seed_knowledge_chain(auth_db, tmp_path / "uploads", target)
    before_ids = [
        [item.id for item in value] if isinstance(value, list) else value.id for value in resources
    ]
    assert_status(
        auth_client.delete(f"/api/admin/users/{target.id}"), 204, "删除账号应软删除并保留资料"
    )
    auth_db.refresh(target)
    assert target.deleted_at is not None and target.status == "disabled"
    page = assert_status(auth_client.get("/api/admin/users"), 200, "删除账号不出现在用户列表")
    assert str(target.id) not in [user["id"] for user in page["items"]]
    for value in resources:
        for item in value if isinstance(value, list) else [value]:
            auth_db.refresh(item)
            assert item.owner_user_id == target.id
    assert [
        [item.id for item in value] if isinstance(value, list) else value.id for value in resources
    ] == before_ids
    assert auth_client.get("/api/parsed-documents").json() == []
    auth_client.cookies.set(SESSION_COOKIE, token)
    assert_error(auth_client.get("/api/users/me"), 401, "auth_required", "删除后目标全部会话失效")
    auth_client.cookies.clear()
    login = auth_client.post(
        "/api/auth/login", json={"email": target.email, "password": DEFAULT_TEST_PASSWORD}
    )
    assert_error(login, 401, "invalid_credentials", "删除账号不得重新登录")


# 验证不存在与已删除目标在重置和删除接口均返回具体业务错误而非泛化 404。
@pytest.mark.parametrize("deleted", [False, True])
def test_missing_targets_return_business_error(auth_client, auth_db, admin_actor, deleted):
    target_id = make_account(auth_db, deleted=True).id if deleted else uuid4()
    for response in (
        auth_client.delete(f"/api/admin/users/{target_id}"),
        auth_client.post(
            f"/api/admin/users/{target_id}/reset-password", json={"new_password": NEW_PASSWORD}
        ),
    ):
        assert_error(response, 404, "user_not_found", "目标不存在或已删除时应说明业务原因")


# 验证新增、重置和删除都经过真实 Cookie 认证、固定角色授权，拒绝后数据库不变。
@pytest.mark.parametrize("role", [None, "member", "viewer"])
def test_lifecycle_rejects_unauthorized_callers(auth_client, auth_db, admin_actor, role):
    target = make_account(auth_db)
    before = auth_db.get(UserCredential, target.id).password_hash
    if role is None:
        auth_client.cookies.clear()
    else:
        login_as(auth_client, auth_db, make_account(auth_db, role=role))
    for response in (
        auth_client.post("/api/admin/users", json=CREATE),
        auth_client.post(
            f"/api/admin/users/{target.id}/reset-password", json={"new_password": NEW_PASSWORD}
        ),
        auth_client.delete(f"/api/admin/users/{target.id}"),
    ):
        assert_error(
            response,
            401 if role is None else 403,
            "auth_required" if role is None else "forbidden",
            "非管理员不得执行账号生命周期操作",
        )
    auth_db.refresh(target)
    assert target.deleted_at is None and target.status == "active"
    assert auth_db.get(UserCredential, target.id).password_hash == before


# 验证跨站建号、重置与删除均被可信来源检查拒绝。
def test_lifecycle_rejects_cross_site_writes(auth_client, auth_db, admin_actor):
    target = make_account(auth_db)
    headers = {"Origin": "https://untrusted.example"}
    for response in (
        auth_client.post("/api/admin/users", json=CREATE, headers=headers),
        auth_client.post(
            f"/api/admin/users/{target.id}/reset-password",
            json={"new_password": NEW_PASSWORD},
            headers=headers,
        ),
        auth_client.delete(f"/api/admin/users/{target.id}", headers=headers),
    ):
        assert_error(response, 403, "csrf_origin_rejected", "跨站后台写入必须拒绝")
