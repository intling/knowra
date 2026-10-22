"""模型配置管理 RED：真实认证、配置 CRUD、密钥与默认绑定契约。"""

from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.main import app
from tests.admin_console.helpers import (
    MODEL_KEY,
    activate_profile,
    assert_error,
    assert_status,
    create_profile,
    profile_payload,
)
from tests.auth_helpers import login_as, make_account, seed_knowledge_chain

KINDS = ("chat", "embedding", "rerank", "query_rewrite")


# 验证四种用途可持久化并分页读取，默认不自动激活，响应不含明文或密文密钥。
@pytest.mark.parametrize("kind", KINDS)
def test_create_and_list_profiles(auth_client, admin_actor, model_settings, kind):
    created = create_profile(auth_client, kind)
    assert created["kind"] == kind and created["has_api_key"] is True
    assert created["enabled"] is True and created["is_default"] is False
    assert {"api_key", "api_key_encrypted"}.isdisjoint(created)
    body = assert_status(
        auth_client.get("/api/admin/models", params={"kind": kind, "offset": 0, "limit": 1}),
        200,
        "模型配置应有可筛选分页列表",
    )
    assert (body["total"], body["offset"], body["limit"]) == (1, 0, 1)
    assert body["items"] == [created]
    assert MODEL_KEY not in str(body)


# 验证空配置列表仍具有稳定的分页响应。
def test_empty_profile_page(auth_client, admin_actor, model_settings):
    body = assert_status(auth_client.get("/api/admin/models"), 200, "首次进入模型管理应显示空列表")
    assert body == {"items": [], "total": 0, "offset": 0, "limit": 20}


# 验证模型地址允许明确配置的本地和私网 HTTP 服务。
@pytest.mark.parametrize("base_url", ["http://localhost:11434/v1", "http://192.168.1.8:8000/v1"])
def test_local_model_endpoints_are_supported(auth_client, admin_actor, model_settings, base_url):
    created = create_profile(auth_client, base_url=base_url, api_key="")
    assert created["base_url"].rstrip("/") == base_url
    assert created["has_api_key"] is False


# 验证地址、枚举、字符串、超时、重试与固定向量维度的边界，不回显提交的秘密。
@pytest.mark.parametrize(
    "changes",
    [
        {"name": " "},
        {"name": "a" * 101},
        {"model": " "},
        {"kind": "unknown"},
        {"base_url": "file:///etc/passwd"},
        {"base_url": "https://username:secret@example.com/v1"},
        {"base_url": "https://models.example/v1?api_key=credential"},
        {"base_url": "https://models.example/v1#fragment"},
        {"timeout_seconds": 0},
        {"timeout_seconds": 121},
        {"max_retries": -1},
        {"max_retries": 4},
        {"kind": "embedding", "dimensions": 1024},
        {"kind": "rerank", "api_format": "unknown", "max_retries": 0},
    ],
)
def test_profile_validation_is_safe(auth_client, admin_actor, model_settings, changes):
    response = auth_client.post("/api/admin/models", json=profile_payload(**changes))
    body = assert_status(response, 422, f"无效模型字段 {list(changes)} 应被拒绝")
    assert body.get("detail"), f"配置校验应包含具体错误原因：{body}"
    assert MODEL_KEY not in response.text
    page = assert_status(auth_client.get("/api/admin/models"), 200, "错误配置不应部分写入")
    assert page["total"] == 0


# 验证分页参数越界必须返回有字段原因的 422。
@pytest.mark.parametrize("params", [{"offset": -1}, {"limit": 0}, {"limit": 101}])
def test_profile_pagination_validation(auth_client, admin_actor, model_settings, params):
    body = assert_status(
        auth_client.get("/api/admin/models", params=params), 422, "分页参数必须有界"
    )
    assert body.get("detail")


# 验证管理员角色获得模型管理权限，其余角色没有该权限。
@pytest.mark.parametrize("role", ["admin", "member", "viewer"])
def test_model_management_permission_is_explicit(auth_client, auth_db, model_settings, role):
    actor = make_account(auth_db, role=role)
    login_as(auth_client, auth_db, actor)
    body = assert_status(auth_client.get("/api/users/me"), 200, "会话应返回角色权限集合")
    assert ("models:manage" in body["permissions"]) is (role == "admin"), (
        "模型配置权限必须显式授予管理员，不能依赖前端隐藏按钮"
    )


# 验证模型所有入口都通过认证和管理员授权，而非只保护列表。
@pytest.mark.parametrize("role", [None, "member", "viewer"])
def test_model_endpoints_reject_unauthorized(auth_client, auth_db, model_settings, role):
    if role is None:
        auth_client.cookies.clear()
    else:
        login_as(auth_client, auth_db, make_account(auth_db, role=role))
    path = f"/api/admin/models/{uuid4()}"
    for response in (
        auth_client.get("/api/admin/models"),
        auth_client.post("/api/admin/models", json=profile_payload()),
        auth_client.patch(path, json={"name": "越权修改"}),
        auth_client.delete(path),
        auth_client.post(path + "/activate"),
        auth_client.post(path + "/deactivate"),
    ):
        assert_error(
            response,
            401 if role is None else 403,
            "auth_required" if role is None else "forbidden",
            "非管理员不得访问任意模型管理接口",
        )


# 验证数据库保存加密密文，不能以明文或简单遮罩形式落库。
def test_api_key_is_encrypted_at_rest(auth_client, auth_db, admin_actor, model_settings):
    create_profile(auth_client)
    encrypted = auth_db.exec(text("SELECT api_key_encrypted FROM model_profiles")).one()[0]
    assert encrypted and encrypted != MODEL_KEY and MODEL_KEY not in encrypted


# 验证省略或留空 key 保留原密钥，显式替换后仍不回显。
@pytest.mark.parametrize(
    "changes", [{"name": "改名"}, {"api_key": ""}, {"api_key": "replacement-test-key"}]
)
def test_edit_preserves_or_replaces_secret(
    auth_client, auth_db, admin_actor, model_settings, changes
):
    profile = create_profile(auth_client)
    original = auth_db.exec(text("SELECT api_key_encrypted FROM model_profiles")).one()[0]
    response = auth_client.patch(f"/api/admin/models/{profile['id']}", json=changes)
    body = assert_status(response, 200, "修改配置必须保留或显式替换密钥")
    assert body["has_api_key"] is True
    assert MODEL_KEY not in response.text and "replacement-test-key" not in response.text
    stored = auth_db.exec(text("SELECT api_key_encrypted FROM model_profiles")).one()[0]
    assert (stored != original) is bool(changes.get("api_key"))


# 验证清除密钥必须显式提交，不能同时提交替换值造成歧义。
def test_clear_secret_is_explicit(auth_client, admin_actor, model_settings):
    profile = create_profile(auth_client)
    path = f"/api/admin/models/{profile['id']}"
    body = assert_status(
        auth_client.patch(path, json={"clear_api_key": True}), 200, "显式清除密钥应成功"
    )
    assert body["has_api_key"] is False
    response = auth_client.patch(path, json={"clear_api_key": True, "api_key": MODEL_KEY})
    invalid = assert_status(response, 422, "清除与替换密钥不可同时提交")
    assert invalid.get("detail") and MODEL_KEY not in response.text


# 验证没有主密钥时秘密写入明确失败，不生成明文或临时密钥。
def test_missing_encryption_key_fails_closed(auth_client, admin_actor, model_settings):
    missing_key_settings = model_settings.model_copy(update={"model_config_encryption_key": ""})
    app.dependency_overrides[get_settings] = lambda: missing_key_settings
    response = auth_client.post("/api/admin/models", json=profile_payload())
    assert_error(response, 503, "model_secret_unavailable", "未配置加密主密钥不得保存秘密")
    assert MODEL_KEY not in response.text


# 验证修改用途或空 PATCH 都被明确拒绝。
def test_kind_is_immutable_and_empty_patch_rejected(auth_client, admin_actor, model_settings):
    profile = create_profile(auth_client)
    path = f"/api/admin/models/{profile['id']}"
    body = assert_status(
        auth_client.patch(path, json={"kind": "embedding"}), 422, "已建配置用途不可修改"
    )
    assert body.get("detail")
    assert_error(auth_client.patch(path, json={}), 422, "empty_update", "空模型更新必须明确拒绝")


# 验证默认切换只影响该用途，取消后恢复无后台默认。
def test_defaults_are_unique_per_kind_and_can_be_reverted(auth_client, admin_actor, model_settings):
    first = create_profile(auth_client, name="聊天一")
    second = create_profile(auth_client, name="聊天二")
    rewrite = create_profile(auth_client, "query_rewrite")
    activate_profile(auth_client, first)
    activate_profile(auth_client, rewrite)
    activate_profile(auth_client, second)
    page = assert_status(auth_client.get("/api/admin/models"), 200, "默认状态必须从持久化绑定读取")
    defaults = {p["id"] for p in page["items"] if p["is_default"]}
    assert defaults == {second["id"], rewrite["id"]}
    body = assert_status(
        auth_client.post(f"/api/admin/models/{second['id']}/deactivate"),
        200,
        "取消当前默认后恢复环境配置",
    )
    assert body["is_default"] is False
    assert_error(
        auth_client.post(f"/api/admin/models/{first['id']}/deactivate"),
        409,
        "model_not_active",
        "非默认配置不可误清其他默认绑定",
    )


# 验证禁用配置无法激活，当前默认不可直接禁用或删除，非默认可删除。
def test_default_and_disabled_profile_protection(auth_client, admin_actor, model_settings):
    profile = create_profile(auth_client, enabled=False)
    path = f"/api/admin/models/{profile['id']}"
    assert_error(
        auth_client.post(path + "/activate"), 409, "model_disabled", "禁用配置不可设为默认"
    )
    assert_status(auth_client.patch(path, json={"enabled": True}), 200, "管理员应可启用配置")
    activate_profile(auth_client, profile)
    assert_error(
        auth_client.patch(path, json={"enabled": False}),
        409,
        "model_in_use",
        "当前默认不能直接禁用",
    )
    assert_error(auth_client.delete(path), 409, "model_in_use", "当前默认不能直接删除")
    assert_status(auth_client.post(path + "/deactivate"), 200, "删除前先恢复环境配置")
    assert_status(auth_client.delete(path), 204, "非默认配置可以删除")
    page = assert_status(auth_client.get("/api/admin/models"), 200, "删除配置应从列表消失")
    assert page["total"] == 0


# 验证模型不存在时所有单项操作都返回具体业务错误。
def test_missing_profile_has_business_error(auth_client, admin_actor, model_settings):
    path = f"/api/admin/models/{uuid4()}"
    for response in (
        auth_client.patch(path, json={"name": "改名"}),
        auth_client.delete(path),
        auth_client.post(path + "/activate"),
        auth_client.post(path + "/deactivate"),
    ):
        assert_error(response, 404, "model_not_found", "不存在模型必须返回具体业务原因")


# 验证已有他人有效向量时不能激活相同维度但不同模型空间的配置。
def test_embedding_activation_rejects_existing_index_conflict(
    auth_client, auth_db, admin_actor, model_settings, tmp_path
):
    owner = make_account(auth_db)
    seed_knowledge_chain(auth_db, tmp_path / "uploads", owner)
    profile = create_profile(auth_client, "embedding", model="different-space-same-dimensions")
    assert_error(
        auth_client.post(f"/api/admin/models/{profile['id']}/activate"),
        409,
        "embedding_index_conflict",
        "相同维度不代表相同向量空间，已有他人索引也需保护",
    )


# 验证已有索引时可更新密钥和超时，但不能编辑默认模型或恢复不同的环境模型。
def test_active_embedding_edit_and_revert_guard(
    auth_client, auth_db, admin_actor, model_settings, tmp_path
):
    profile = create_profile(auth_client, "embedding", model="Qwen/Qwen3-Embedding-4B")
    activate_profile(auth_client, profile)
    seed_knowledge_chain(auth_db, tmp_path / "uploads", admin_actor)
    path = f"/api/admin/models/{profile['id']}"
    assert_status(
        auth_client.patch(path, json={"timeout_seconds": 30, "api_key": "new-embedding-test-key"}),
        200,
        "不改变空间的超时和密钥调整应允许",
    )
    assert_error(
        auth_client.patch(path, json={"model": "different-embedding"}),
        409,
        "embedding_index_conflict",
        "默认模型编辑不能绕过索引保护",
    )
    assert_error(
        auth_client.post(path + "/deactivate"),
        409,
        "embedding_index_conflict",
        "恢复不同环境地址也不能绕过索引保护",
    )


# 验证模型写操作同样遵循可信来源检查。
def test_model_writes_require_trusted_origin(auth_client, admin_actor, model_settings):
    response = auth_client.post(
        "/api/admin/models", json=profile_payload(), headers={"Origin": "https://untrusted.example"}
    )
    assert_error(response, 403, "csrf_origin_rejected", "跨站模型配置写入必须拒绝")


# 验证模型写入与切换的应用日志不记录提交密钥、密文或加密主密钥。
def test_model_logs_exclude_all_secrets(auth_client, auth_db, admin_actor, model_settings, caplog):
    profile = create_profile(auth_client)
    activate_profile(auth_client, profile)
    auth_client.patch(
        f"/api/admin/models/{profile['id']}", json={"api_key": "replacement-log-secret"}
    )
    encrypted = auth_db.exec(text("SELECT api_key_encrypted FROM model_profiles")).one()[0]
    for secret in (
        MODEL_KEY,
        "replacement-log-secret",
        encrypted,
        model_settings.model_config_encryption_key,
    ):
        assert secret not in caplog.text


# 验证尚未完成的旧空间任务同样阻止模型切换。
@pytest.mark.parametrize("job_status", ["queued", "running"])
def test_embedding_pending_jobs_block_switch(
    auth_client, auth_db, admin_actor, model_settings, tmp_path, job_status
):
    from sqlmodel import select

    from app.models.document_embedding import DocumentEmbeddingJob

    seed_knowledge_chain(auth_db, tmp_path / "uploads", admin_actor)
    job = auth_db.exec(select(DocumentEmbeddingJob)).one()
    job.status = job_status
    auth_db.add(job)
    auth_db.commit()
    profile = create_profile(auth_client, "embedding", model="new-space")
    assert_error(
        auth_client.post(f"/api/admin/models/{profile['id']}/activate"),
        409,
        "embedding_index_conflict",
        "未完成任务必须保护旧向量空间",
    )
