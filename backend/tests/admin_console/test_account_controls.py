"""滚动额度与退出设备：账号保护、严格输入和审计原子性。"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlmodel import select

from app.core.errors import AppError
from app.models.admin_operations import AdminAuditEvent
from app.models.chat_quota import ChatUsage, UserChatLimit
from app.models.user import UserSession
from app.services import chat_quota, user_admin
from tests.admin_console.helpers import assert_error, assert_status
from tests.admin_console.test_audit_transactions import reject_audit_inserts
from tests.auth_helpers import issue_session_token, login_as, make_account


# 验证严格整数、上下界、null 与必填字段，不接受 bool、字符串或小数的隐式转换。
@pytest.mark.parametrize("value", [0, -1, 100001, True, False, "3", 2.5, {}, []])
def test_quota_rejects_invalid_input(auth_client, auth_db, admin_actor, value):
    user = make_account(auth_db)
    body = assert_status(
        auth_client.put(f"/api/admin/users/{user.id}/chat-limit", json={"hourly_limit": value}),
        422,
        "非法额度必须明确拒绝",
    )
    assert body["detail"], "额度校验必须提供原因"


# 验证额度在 null/边界间切换，返回可解释的 UTC 快照且每次修改被审计。
@pytest.mark.parametrize("value", [None, 1, 100000])
def test_quota_write_and_read_snapshot(auth_client, auth_db, admin_actor, value):
    user = make_account(auth_db)
    path = f"/api/admin/users/{user.id}/chat-limit"
    written = assert_status(
        auth_client.put(path, json={"hourly_limit": value}), 200, "管理员应可设置额度"
    )
    read = assert_status(auth_client.get(path), 200, "管理员应可查看额度")
    assert written["hourly_limit"] == read["hourly_limit"] == value
    assert read["occupied_slots"] == (None if value is None else 0)
    assert read["remaining"] == value and read["window_seconds"] == 3600
    assert datetime.fromisoformat(read["observed_at"]).tzinfo is not None
    rows = auth_db.exec(select(AdminAuditEvent)).all()
    assert (
        len(rows) == 1
        and rows[0].action == "user.chat_limit.update"
        and rows[0].result == "success"
    )


# 验证收紧/放宽/取消/重新设限保留全部旧预留，失败释放只影响对应预留。
def test_quota_changes_keep_reservations_and_do_not_backfill(auth_client, auth_db, admin_actor):
    user = make_account(auth_db)
    path = f"/api/admin/users/{user.id}/chat-limit"
    assert chat_quota.reserve_chat(auth_db, user.id) is None
    assert not auth_db.exec(select(ChatUsage)).all(), "不限额请求不能补记"
    assert_status(auth_client.put(path, json={"hourly_limit": 3}), 200, "首次设限")
    ids = [chat_quota.reserve_chat(auth_db, user.id) for _ in range(3)]
    for value, remaining in [(2, 0), (5, 2), (None, None), (4, 1)]:
        body = assert_status(
            auth_client.put(path, json={"hourly_limit": value}), 200, "切换限额应保留历史预留"
        )
        assert body["remaining"] == remaining
        assert {row.id for row in auth_db.exec(select(ChatUsage)).all()} == set(ids)
    chat_quota.release_chat(auth_db, ids[0])
    assert_status(auth_client.put(path, json={"hourly_limit": 1}), 200, "收紧到低于占用应成功")
    with pytest.raises(AppError) as caught:
        chat_quota.reserve_chat(auth_db, user.id)
    assert caught.value.code == "chat_quota_exceeded"
    event = auth_db.exec(
        select(AdminAuditEvent).order_by(AdminAuditEvent.created_at.desc())
    ).first()
    assert event.changes_json == {"hourly_limit": {"before": 4, "after": 1}}


# 验证撤销仅修改有效会话，重复为零，密码、状态、角色和过期会话均保留。
def test_revoke_live_sessions_and_repeat(auth_client, auth_db, admin_actor):
    user = make_account(auth_db)
    for _ in range(3):
        issue_session_token(auth_db, user)
    sessions = auth_db.exec(select(UserSession).where(UserSession.user_id == user.id)).all()
    sessions[0].expires_at = datetime.now(UTC) - timedelta(seconds=1)
    auth_db.add(sessions[0])
    auth_db.commit()
    path = f"/api/admin/users/{user.id}/revoke-sessions"
    assert assert_status(auth_client.post(path), 200, "撤销全部有效设备会话") == {
        "revoked_count": 2
    }
    assert assert_status(auth_client.post(path), 200, "重复撤销应成功") == {"revoked_count": 0}
    auth_db.refresh(sessions[0])
    assert sessions[0].revoked_at is None, "过期会话不属于本次有效会话计数"
    auth_db.refresh(user)
    assert user.role == "member" and user.status == "active"
    events = auth_db.exec(select(AdminAuditEvent).order_by(AdminAuditEvent.created_at)).all()
    assert [e.changes_json for e in events] == [{"revoked_count": 2}, {"revoked_count": 0}]


# 验证自己退出设备应引导账户入口，不能破坏当前管理会话。
def test_revoke_self_is_rejected(auth_client, admin_actor):
    assert_error(
        auth_client.post(f"/api/admin/users/{admin_actor.id}/revoke-sessions"),
        409,
        "cannot_revoke_self_sessions",
        "自身撤销必须使用账户操作",
    )


# 验证匿名、成员和只读角色均无额度及会话管理权限。
@pytest.mark.parametrize("role", [None, "member", "viewer"])
@pytest.mark.parametrize("operation", ["get", "put", "revoke"])
def test_account_controls_require_admin(auth_client, auth_db, role, operation):
    user = make_account(auth_db)
    if role:
        login_as(auth_client, auth_db, make_account(auth_db, role=role))
    else:
        auth_client.cookies.clear()
    path = f"/api/admin/users/{user.id}"
    response = (
        auth_client.post(path + "/revoke-sessions")
        if operation == "revoke"
        else auth_client.request(
            operation,
            path + "/chat-limit",
            json={"hourly_limit": 2} if operation == "put" else None,
        )
    )
    assert_error(
        response,
        403 if role else 401,
        "forbidden" if role else "auth_required",
        "必须使用服务端管理权限",
    )


# 验证审计不可写时额度修改和会话撤销同时回滚。
@pytest.mark.parametrize("operation", ["quota", "sessions"])
def test_control_audit_failure_rolls_back(auth_client, auth_db, admin_actor, operation):
    user = make_account(auth_db)
    issue_session_token(auth_db, user)
    with reject_audit_inserts(auth_db):
        response = (
            auth_client.put(f"/api/admin/users/{user.id}/chat-limit", json={"hourly_limit": 2})
            if operation == "quota"
            else auth_client.post(f"/api/admin/users/{user.id}/revoke-sessions")
        )
        assert_error(response, 503, "admin_audit_unavailable", "成功审计失败必须回滚业务")
    assert auth_db.get(UserChatLimit, user.id) is None
    assert all(
        s.revoked_at is None
        for s in auth_db.exec(select(UserSession).where(UserSession.user_id == user.id)).all()
    )


# 验证在途失权与已删除目标均由事务内重新核验，不能保留半提交。
@pytest.mark.parametrize("operation", ["quota", "sessions"])
def test_control_revalidates_actor_and_target(auth_client, auth_db, admin_actor, operation):
    user = make_account(auth_db, deleted=True)
    path = f"/api/admin/users/{user.id}"
    response = (
        auth_client.put(path + "/chat-limit", json={"hourly_limit": 3})
        if operation == "quota"
        else auth_client.post(path + "/revoke-sessions")
    )
    assert_error(response, 404, "user_not_found", "软删除对象不可管理")
    actor_id = admin_actor.id
    auth_db.execute(text("UPDATE users SET role='member' WHERE id=:id"), {"id": actor_id.hex})
    auth_db.commit()
    with pytest.raises(AppError) as caught:
        if operation == "quota":
            user_admin.set_chat_limit(auth_db, admin_actor, user.id, 3)
        else:
            user_admin.revoke_sessions(auth_db, admin_actor, user.id)
    assert caught.value.code == "forbidden", "服务层必须重验失权操作者"
