"""后台改版第二批 RED：原管理写操作的原子审计、安全投影及失败留痕。"""

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlmodel import select

from app.core.config import get_settings
from app.core.errors import AppError
from app.main import app
from app.models import base
from app.models.admin_operations import AdminAuditEvent
from app.models.model_configuration import ModelBinding, ModelProfile
from app.models.user import User, UserCredential, UserSession
from app.schemas.auth import AdminUserUpdate
from app.services import user_admin
from tests.admin_console.helpers import (
    MODEL_KEY,
    activate_profile,
    assert_error,
    assert_status,
    create_profile,
    profile_payload,
)
from tests.auth_helpers import (
    DEFAULT_TEST_PASSWORD,
    issue_session_token,
    make_account,
    seed_knowledge_chain,
)

EXISTING_ACTIONS = (
    "user.create",
    "user.update",
    "user.reset_password",
    "user.delete",
    "model.create",
    "model.update",
    "model.activate",
    "model.deactivate",
    "model.delete",
)
MODEL_DIFF_FIELDS = {
    "kind",
    "model",
    "enabled",
    "timeout_seconds",
    "max_retries",
    "dimensions",
    "api_format",
    "revision",
    "secret_changed",
    "endpoint_changed",
}
ALLOWED_CHANGES = {
    "user.create": {"role", "status"},
    "user.update": {"role", "status"},
    "user.reset_password": set(),
    "user.delete": {"status", "deleted"},
    "model.create": MODEL_DIFF_FIELDS,
    "model.update": MODEL_DIFF_FIELDS,
    "model.delete": MODEL_DIFF_FIELDS,
    "model.activate": {"kind", "default_profile_id", "binding_revision"},
    "model.deactivate": {"kind", "default_profile_id", "binding_revision"},
}
CREATE_EMAIL = "audit-new-user@example.com"
NEW_PASSWORD = "Audit-Reset-2026"
REPLACEMENT_KEY = "audit-replacement-secret-canary"
SINK_ERROR = "audit-sink-error-canary-must-not-be-logged"


def audit_events(session, *, trace_id=None):
    # 从真实历史表读取，避免用 logger mock 代替持久化与事务断言。
    query = select(AdminAuditEvent).order_by(AdminAuditEvent.created_at, AdminAuditEvent.id)
    if trace_id is not None:
        query = query.where(AdminAuditEvent.trace_id == trace_id)
    return list(session.exec(query).all())


def only_event(session, trace_id, action, result):
    rows = audit_events(session, trace_id=trace_id)
    assert len(rows) == 1, (
        f"{action} 请求必须持久化且仅持久化一条 {result} 审计，"
        f"实际为 {len(rows)} 条；业务成功或失败不能只写应用日志。"
    )
    row = rows[0]
    assert (row.action, row.result) == (action, result), (
        f"管理审计必须反映实际动作和事务结果，实际为 {row.action}/{row.result}。"
    )
    return row


def assert_safe_diff(row):
    changes = row.changes_json
    assert set(changes) <= ALLOWED_CHANGES[row.action], (
        f"{row.action} 审计超出动作字段白名单：{set(changes) - ALLOWED_CHANGES[row.action]}。"
    )
    for field, change in changes.items():
        if field in {"secret_changed", "endpoint_changed"}:
            assert type(change) is bool, f"{field} 只能记录布尔变化，不能保存原值。"
        else:
            assert isinstance(change, dict) and set(change) == {"before", "after"}, (
                f"{row.action}.{field} 必须提供安全的前后值，不能直接复制请求对象。"
            )
            assert change["before"] != change["after"], (
                f"{row.action}.{field} 没有发生变化，不应作为变更记入台账。"
            )


@contextmanager
def reject_audit_inserts(session):
    # 用数据库触发器拒绝真实 INSERT，不依赖未来审计服务的内部函数名。
    session.execute(
        text(
            "CREATE TRIGGER reject_admin_audit BEFORE INSERT ON admin_audit_events "
            f"BEGIN SELECT RAISE(ABORT, '{SINK_ERROR}'); END"
        )
    )
    session.commit()
    try:
        yield
    finally:
        session.rollback()
        session.execute(text("DROP TRIGGER reject_admin_audit"))
        session.commit()


def business_snapshot(session):
    # 比较全部业务表的已持久化值，覆盖密码、会话、删除状态及模型绑定版本。
    return {
        table.name: session.execute(select(table).order_by(*table.primary_key.columns))
        .mappings()
        .all()
        for table in base.metadata.sorted_tables
        if table.name != "admin_audit_events"
    }


@pytest.fixture
def operation_setup(auth_db, admin_actor, model_settings):
    # 直接准备旧业务状态，不经新增审计路径，避免把前置失败当成被测行为失败。
    target = make_account(auth_db, email="audit-target@example.com")
    tokens = [issue_session_token(auth_db, target) for _ in range(2)]
    profile = ModelProfile(
        name="不应入审计的配置显示名",
        kind="chat",
        base_url="https://private-model.example/v1/endpoint-canary",
        model="audit-chat",
        api_key_encrypted=Fernet(model_settings.model_config_encryption_key.encode())
        .encrypt(MODEL_KEY.encode())
        .decode(),
        timeout_seconds=12,
        max_retries=1,
    )
    auth_db.add(profile)
    auth_db.add(ModelBinding(kind="chat", revision=7))
    auth_db.commit()
    return {"target": target, "tokens": tokens, "profile": profile}


def operation_request(session, setup, action):
    # 每个映射只触发一个既有管理写操作；创建对象 UUID 从成功响应获得。
    target, profile = setup["target"], setup["profile"]
    user_path, model_path = f"/api/admin/users/{target.id}", f"/api/admin/models/{profile.id}"
    if action == "model.deactivate":
        binding = session.get(ModelBinding, "chat")
        binding.profile_id = profile.id
        session.add(binding)
        session.commit()
    requests = {
        "user.create": (
            "POST",
            "/api/admin/users",
            {
                "email": CREATE_EMAIL,
                "display_name": "不应入审计的新用户显示名",
                "password": DEFAULT_TEST_PASSWORD,
                "role": "viewer",
            },
            201,
            None,
        ),
        "user.update": (
            "PATCH",
            user_path,
            {"role": "viewer", "status": "disabled"},
            200,
            target.id,
        ),
        "user.reset_password": (
            "POST",
            user_path + "/reset-password",
            {"new_password": NEW_PASSWORD},
            204,
            target.id,
        ),
        "user.delete": ("DELETE", user_path, None, 204, target.id),
        "model.create": ("POST", "/api/admin/models", profile_payload(), 201, None),
        "model.update": (
            "PATCH",
            model_path,
            {
                "name": "另一个不应入审计的显示名",
                "model": "audit-chat-v2",
                "base_url": "https://replacement.example/v1/new-endpoint-canary",
                "timeout_seconds": 20,
                "max_retries": 0,
                "api_key": REPLACEMENT_KEY,
            },
            200,
            profile.id,
        ),
        "model.activate": ("POST", model_path + "/activate", None, 200, profile.id),
        "model.deactivate": ("POST", model_path + "/deactivate", None, 200, profile.id),
        "model.delete": ("DELETE", model_path, None, 204, profile.id),
    }
    return requests[action]


# 验证原有九类成功写操作各持久化一条审计，操作者、资源、trace、时间和安全前后值准确。
@pytest.mark.parametrize("action", EXISTING_ACTIONS)
def test_existing_admin_writes_commit_exactly_one_safe_event(
    auth_client, auth_db, admin_actor, operation_setup, action
):
    method, path, payload, status, resource_id = operation_request(auth_db, operation_setup, action)
    trace_id = str(uuid4())
    started = datetime.now(UTC)
    response = auth_client.request(method, path, json=payload, headers={"X-Trace-ID": trace_id})
    body = assert_status(response, status, f"{action} 必须保留原有成功响应")
    if resource_id is None:
        resource_id = UUID(body["id"])
    auth_db.rollback()
    row = only_event(auth_db, trace_id, action, "success")
    assert (row.actor_user_id, row.resource_type, row.resource_id) == (
        admin_actor.id,
        action.split(".")[0],
        resource_id,
    ), "审计必须记录服务端身份和实际操作对象，不能使用客户端归属。"
    assert row.error_code is None, "成功审计不得包含失败错误码。"
    timestamp = (
        row.created_at.replace(tzinfo=UTC) if row.created_at.tzinfo is None else row.created_at
    )
    assert started <= timestamp <= datetime.now(UTC), "审计时间必须对应实际提交时段。"
    assert_safe_diff(row)
    if action == "user.create":
        assert row.changes_json == {
            "role": {"before": None, "after": "viewer"},
            "status": {"before": None, "after": "active"},
        }
    elif action == "user.update":
        assert row.changes_json == {
            "role": {"before": "member", "after": "viewer"},
            "status": {"before": "active", "after": "disabled"},
        }
    elif action == "user.delete":
        assert row.changes_json == {
            "status": {"before": "active", "after": "disabled"},
            "deleted": {"before": False, "after": True},
        }
    elif action == "model.update":
        assert row.changes_json["model"] == {"before": "audit-chat", "after": "audit-chat-v2"}
        assert row.changes_json["secret_changed"] is True
        assert row.changes_json["endpoint_changed"] is True
    elif action in {"model.activate", "model.deactivate"}:
        profile_id = str(resource_id)
        before, after = (None, profile_id) if action == "model.activate" else (profile_id, None)
        assert row.changes_json["default_profile_id"] == {"before": before, "after": after}
        assert row.changes_json["binding_revision"] == {"before": 7, "after": 8}
    if action == "model.delete":
        assert auth_db.get(ModelProfile, resource_id) is None, "删除模型不能级联丢弃原资源审计。"


# 验证四用途模型的整个配置生命周期只记录动作白名单，不保存显示名、完整地址及任何密钥材料。
@pytest.mark.parametrize("kind", ["chat", "embedding", "rerank", "query_rewrite"])
def test_model_audit_excludes_endpoint_names_and_all_secret_material(
    auth_client, auth_db, admin_actor, model_settings, kind
):
    private_name = f"private-{kind}-profile-name-canary"
    private_url = f"https://private.example/v1/{kind}-endpoint-canary"
    profile = create_profile(auth_client, kind, name=private_name, base_url=private_url)
    profile_id = UUID(profile["id"])
    ciphertexts = [auth_db.get(ModelProfile, profile_id).api_key_encrypted]
    assert_status(
        auth_client.patch(
            f"/api/admin/models/{profile_id}",
            json={
                "api_key": REPLACEMENT_KEY,
                "timeout_seconds": 20,
            },
        ),
        200,
        "密钥替换应可审计但不保存值",
    )
    auth_db.expire_all()
    ciphertexts.append(auth_db.get(ModelProfile, profile_id).api_key_encrypted)
    activate_profile(auth_client, profile)
    assert_status(
        auth_client.post(f"/api/admin/models/{profile_id}/deactivate"), 200, "取消默认留痕"
    )
    assert_status(
        auth_client.delete(f"/api/admin/models/{profile_id}"), 204, "删除配置保留安全历史"
    )
    rows = audit_events(auth_db)
    assert len(rows) == 5, f"{kind} 配置的五次成功操作都必须持久化审计，实际 {len(rows)} 条。"
    stored = json.dumps([row.model_dump(mode="json") for row in rows], ensure_ascii=False)
    for secret in [
        MODEL_KEY,
        REPLACEMENT_KEY,
        private_name,
        private_url,
        model_settings.model_config_encryption_key,
        *ciphertexts,
    ]:
        assert secret not in stored, "管理台账保存了名称、地址或密钥材料，应按动作白名单裁剪。"
    for row in rows:
        assert_safe_diff(row)
        assert row.resource_id == profile_id, "模型物理删除后历史资源 ID 仍需保持。"


# 验证账号生命周期的审计不含邮箱、显示名、密码/哈希、会话材料及完整私有文档链路内容。
def test_account_audit_excludes_credentials_sessions_and_private_documents(
    auth_client, auth_db, admin_actor, tmp_path
):
    private_name = "private-account-name-canary"
    user = assert_status(
        auth_client.post(
            "/api/admin/users",
            json={
                "email": CREATE_EMAIL,
                "display_name": private_name,
                "password": DEFAULT_TEST_PASSWORD,
            },
        ),
        201,
        "准备账号生命周期审计",
    )
    user_id = UUID(user["id"])
    target = auth_db.get(User, user_id)
    tokens = [issue_session_token(auth_db, target) for _ in range(2)]
    hashes = [auth_db.get(UserCredential, user_id).password_hash]
    token_hashes = [
        row.token_hash
        for row in auth_db.exec(select(UserSession).where(UserSession.user_id == user_id)).all()
    ]
    upload, parsed, _job, chunks, _vectors = seed_knowledge_chain(auth_db, tmp_path, target)
    private_values = [
        upload.original_filename,
        upload.storage_key,
        chunks[0].text,
        chunks[0].contextualized_text,
        str(parsed.id),
    ]
    assert_status(
        auth_client.post(
            f"/api/admin/users/{user_id}/reset-password",
            json={
                "new_password": NEW_PASSWORD,
            },
        ),
        204,
        "重置密码只记录动作",
    )
    auth_db.expire_all()
    hashes.append(auth_db.get(UserCredential, user_id).password_hash)
    assert_status(
        auth_client.patch(
            f"/api/admin/users/{user_id}",
            json={
                "role": "viewer",
                "status": "disabled",
            },
        ),
        200,
        "角色与状态前后值安全留痕",
    )
    assert_status(auth_client.delete(f"/api/admin/users/{user_id}"), 204, "软删除保留审计")
    rows = audit_events(auth_db)
    assert len(rows) == 4, "账号创建、重置、更新和删除应有四条持久审计，不能只输出应用日志。"
    stored = json.dumps([row.model_dump(mode="json") for row in rows], ensure_ascii=False)
    for secret in [
        CREATE_EMAIL,
        private_name,
        DEFAULT_TEST_PASSWORD,
        NEW_PASSWORD,
        *tokens,
        *hashes,
        *token_hashes,
        *private_values,
    ]:
        assert secret not in stored, "账号审计泄露了身份显示信息、凭据或私有资料。"
    for row in rows:
        assert_safe_diff(row)
    reset = next(row for row in rows if row.action == "user.reset_password")
    assert reset.changes_json == {}, "密码重置不能保存前后密码、哈希或会话材料。"


# 验证留空密钥不算替换，改名不入审计，替换/清除密钥及地址修改只保留布尔变化。
@pytest.mark.parametrize(
    "payload,secret_changed,endpoint_changed",
    [
        ({"name": "display-name-canary-only"}, False, False),
        ({"api_key": ""}, False, False),
        ({"api_key": REPLACEMENT_KEY}, True, False),
        ({"clear_api_key": True}, True, False),
        ({"base_url": "https://replacement.example/v1/endpoint-canary"}, False, True),
    ],
)
def test_model_audit_distinguishes_secret_and_endpoint_intent(
    auth_client, auth_db, operation_setup, payload, secret_changed, endpoint_changed
):
    trace_id = str(uuid4())
    profile_id = operation_setup["profile"].id
    assert_status(
        auth_client.patch(
            f"/api/admin/models/{profile_id}", json=payload, headers={"X-Trace-ID": trace_id}
        ),
        200,
        "配置更新保留兼容语义",
    )
    row = only_event(auth_db, trace_id, "model.update", "success")
    assert row.changes_json.get("secret_changed", False) is secret_changed
    assert row.changes_json.get("endpoint_changed", False) is endpoint_changed
    assert_safe_diff(row)


DENIAL_CASES = (
    "last_admin",
    "cannot_disable_self",
    "cannot_reset_self",
    "cannot_delete_self",
    "email_conflict",
    "weak_password",
    "user_not_found",
    "empty_update",
    "model_disabled",
    "model_in_use",
    "model_not_active",
    "model_not_found",
)


def denied_request(session, setup, actor_id, code):
    target, profile = setup["target"], setup["profile"]
    user_path, model_path = f"/api/admin/users/{target.id}", f"/api/admin/models/{profile.id}"
    if code == "model_disabled":
        profile.enabled = False
        session.add(profile)
        session.commit()
    if code == "model_in_use":
        binding = session.get(ModelBinding, "chat")
        binding.profile_id = profile.id
        session.add(binding)
        session.commit()
    absent_user, absent_model = uuid4(), uuid4()
    cases = {
        "last_admin": (
            "PATCH",
            f"/api/admin/users/{actor_id}",
            {"role": "member"},
            409,
            "user.update",
            actor_id,
        ),
        "cannot_disable_self": (
            "PATCH",
            f"/api/admin/users/{actor_id}",
            {"status": "disabled"},
            409,
            "user.update",
            actor_id,
        ),
        "cannot_reset_self": (
            "POST",
            f"/api/admin/users/{actor_id}/reset-password",
            {"new_password": NEW_PASSWORD},
            409,
            "user.reset_password",
            actor_id,
        ),
        "cannot_delete_self": (
            "DELETE",
            f"/api/admin/users/{actor_id}",
            None,
            409,
            "user.delete",
            actor_id,
        ),
        "email_conflict": (
            "POST",
            "/api/admin/users",
            {"email": target.email, "display_name": "冲突尝试", "password": DEFAULT_TEST_PASSWORD},
            409,
            "user.create",
            None,
        ),
        "weak_password": (
            "POST",
            user_path + "/reset-password",
            {"new_password": "short"},
            422,
            "user.reset_password",
            target.id,
        ),
        "user_not_found": (
            "PATCH",
            f"/api/admin/users/{absent_user}",
            {"role": "viewer"},
            404,
            "user.update",
            absent_user,
        ),
        "empty_update": ("PATCH", user_path, {}, 422, "user.update", target.id),
        "model_disabled": (
            "POST",
            model_path + "/activate",
            None,
            409,
            "model.activate",
            profile.id,
        ),
        "model_in_use": ("DELETE", model_path, None, 409, "model.delete", profile.id),
        "model_not_active": (
            "POST",
            model_path + "/deactivate",
            None,
            409,
            "model.deactivate",
            profile.id,
        ),
        "model_not_found": (
            "PATCH",
            f"/api/admin/models/{absent_model}",
            {"name": "不存在"},
            404,
            "model.update",
            absent_model,
        ),
    }
    return cases[code]


# 验证业务拒绝回滚后独立持久化 denied，保留原错误原因、不保存请求意图、不误记成功。
@pytest.mark.parametrize("code", DENIAL_CASES)
def test_business_denial_is_persisted_after_rollback(
    auth_client, auth_db, admin_actor, operation_setup, code
):
    method, path, payload, status, action, resource_id = denied_request(
        auth_db, operation_setup, admin_actor.id, code
    )
    before = business_snapshot(auth_db)
    trace_id = str(uuid4())
    assert_error(
        auth_client.request(method, path, json=payload, headers={"X-Trace-ID": trace_id}),
        status,
        code,
        f"{code} 不能被审计包装替换为笼统错误",
    )
    auth_db.rollback()
    assert business_snapshot(auth_db) == before, f"{code} 拒绝后业务数据应保持原样。"
    row = only_event(auth_db, trace_id, action, "denied")
    assert row.actor_user_id == admin_actor.id and row.error_code == code
    assert row.changes_json == {}, "拒绝请求不能把意图记作已发生的前后值。"
    if resource_id is not None:
        assert row.resource_id == resource_id, "拒绝事件必须关联原请求对象。"
    else:
        assert row.resource_id != operation_setup["target"].id, "冲突建号不能绑定既有账号归属。"


# 验证依赖不可用记录 failed，不丢失 503 错误语义且没有模型、密钥或绑定的部分写入。
def test_dependency_failure_records_failed_without_partial_model_write(
    auth_client, auth_db, admin_actor, model_settings
):
    app.dependency_overrides[get_settings] = lambda: model_settings.model_copy(
        update={"model_config_encryption_key": ""}
    )
    trace_id = str(uuid4())
    before = business_snapshot(auth_db)
    assert_error(
        auth_client.post(
            "/api/admin/models", json=profile_payload(), headers={"X-Trace-ID": trace_id}
        ),
        503,
        "model_secret_unavailable",
        "缺少加密主密钥仍应返回具体依赖错误",
    )
    auth_db.rollback()
    assert business_snapshot(auth_db) == before, "密钥依赖失败不能创建半成品模型配置。"
    row = only_event(auth_db, trace_id, "model.create", "failed")
    assert row.error_code == "model_secret_unavailable" and row.changes_json == {}


# 验证审计真实 INSERT 失败时九类业务写入全部回滚，包含凭据、会话、删除状态和绑定版本。
@pytest.mark.parametrize("action", EXISTING_ACTIONS)
def test_unwritable_audit_rolls_back_entire_business_transaction(
    auth_client, auth_db, operation_setup, action
):
    method, path, payload, _status, _resource_id = operation_request(
        auth_db, operation_setup, action
    )
    before = business_snapshot(auth_db)
    with reject_audit_inserts(auth_db):
        response = auth_client.request(method, path, json=payload)
        assert_error(
            response,
            503,
            "admin_audit_unavailable",
            f"{action} 审计不可写时必须整体失败，不能先提交业务再补写日志",
        )
        assert SINK_ERROR not in response.text, "审计故障响应不能暴露数据库异常原文。"
        auth_db.rollback()
        assert business_snapshot(auth_db) == before, f"{action} 留下了未审计的业务变更。"
        assert not audit_events(auth_db), "失败事务不能残留成功审计。"


# 验证失败事务回滚后重试只留下最终的一条成功事件，不残留已回滚事件或半提交对象。
@pytest.mark.parametrize("action", ["user.create", "user.update", "model.activate"])
def test_rolled_back_attempt_then_retry_keeps_one_committed_success(
    auth_client, auth_db, operation_setup, action
):
    method, path, payload, status, _resource_id = operation_request(
        auth_db, operation_setup, action
    )
    trace_id = str(uuid4())
    with reject_audit_inserts(auth_db):
        assert_error(
            auth_client.request(method, path, json=payload, headers={"X-Trace-ID": trace_id}),
            503,
            "admin_audit_unavailable",
            "首次事务必须因审计不可写回滚",
        )
    assert_status(
        auth_client.request(method, path, json=payload, headers={"X-Trace-ID": trace_id}),
        status,
        "解除审计故障后重试应可正常提交",
    )
    rows = [row for row in audit_events(auth_db, trace_id=trace_id) if row.result == "success"]
    assert len(rows) == 1 and rows[0].action == action, "事务回滚重试不能重复成功记账。"


# 验证 trace 只用于关联，两个独立成功请求即使使用同一 trace 也必须分别留痕。
def test_shared_trace_does_not_deduplicate_distinct_successful_changes(
    auth_client, auth_db, operation_setup
):
    trace_id = str(uuid4())
    path = f"/api/admin/users/{operation_setup['target'].id}"
    for role in ["viewer", "member"]:
        assert_status(
            auth_client.patch(path, json={"role": role}, headers={"X-Trace-ID": trace_id}),
            200,
            "同 trace 下的独立角色变更都应正常提交",
        )
    rows = audit_events(auth_db, trace_id=trace_id)
    assert len(rows) == 2 and all(row.result == "success" for row in rows), (
        "trace ID 不能充当幂等键而静默丢弃第二个已提交变更的审计。"
    )
    assert rows[0].id != rows[1].id
    assert {json.dumps(row.changes_json, sort_keys=True) for row in rows} == {
        json.dumps({"role": {"before": "member", "after": "viewer"}}, sort_keys=True),
        json.dumps({"role": {"before": "viewer", "after": "member"}}, sort_keys=True),
    }


# 验证在途操作者失权由事务内重新校验，并在独立事务记录拒绝，不修改目标账号。
def test_inflight_actor_losing_admin_role_records_denial(auth_db, operation_setup, admin_actor):
    actor_id = admin_actor.id
    target_id = operation_setup["target"].id
    auth_db.execute(text("UPDATE users SET role = 'member' WHERE id = :id"), {"id": actor_id.hex})
    auth_db.commit()
    with pytest.raises(AppError) as caught:
        user_admin.update_user(auth_db, admin_actor, target_id, AdminUserUpdate(role="viewer"))
    assert caught.value.status_code == 403 and caught.value.code == "forbidden", (
        "提交前失权必须返回明确权限拒绝，不能沿用请求初始身份。"
    )
    auth_db.rollback()
    assert auth_db.get(User, target_id).role == "member", "失权操作者不能修改目标角色。"
    rows = audit_events(auth_db)
    assert len(rows) == 1 and rows[0].result == "denied", "在途失权需要持久化拒绝审计。"
    assert rows[0].actor_user_id == actor_id and rows[0].error_code == "forbidden"


# 验证拒绝事件也不可写时保留原 409，并用固定事件和安全字段记录故障，不输出异常及秘密。
def test_failure_audit_outage_preserves_original_error_and_logs_safe_event(
    auth_client, auth_db, admin_actor, caplog
):
    caplog.set_level("WARNING")
    with reject_audit_inserts(auth_db):
        assert_error(
            auth_client.patch(f"/api/admin/users/{admin_actor.id}", json={"role": "member"}),
            409,
            "last_admin",
            "失败审计故障不能覆盖最后管理员保护错误",
        )
    assert "管理失败审计写入失败" in caplog.text, "失败留痕不可写时需要固定结构化故障事件。"
    assert SINK_ERROR not in caplog.text, "审计降级日志不能复制数据库异常原文。"
    assert DEFAULT_TEST_PASSWORD not in caplog.text, "审计降级日志不能包含请求密码。"
