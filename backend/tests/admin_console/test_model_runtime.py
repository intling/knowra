"""运行时配置 RED：下一次请求生效、环境回退、用途隔离与解密失败。"""

from importlib import import_module

import pytest

from tests.admin_console.helpers import MODEL_KEY, activate_profile, create_profile


def resolve(session, settings):
    # 测试只在函数执行时导入待实现服务，避免整个测试集因缺失模块而无法收集。
    module = import_module("app.services.model_configuration")
    return module.resolve_model_settings(session, settings)


# 验证无后台默认时完整沿用环境配置，并且返回副本而不修改缓存的环境对象。
def test_unbound_profiles_preserve_environment(auth_db, model_settings):
    before = model_settings.model_dump()
    effective = resolve(auth_db, model_settings)
    assert effective is not model_settings
    for key, value in before.items():
        assert getattr(effective, key) == value, f"无绑定时环境字段 {key} 不应变化"
    assert model_settings.model_dump() == before


# 验证四类模型各自映射正确的地址、模型、密钥和超时，且激活只影响对应用途。
@pytest.mark.parametrize(
    "kind,prefix,timeout_field",
    [
        ("chat", "chat", "chat_request_timeout"),
        ("embedding", "document_embedding", "document_embedding_request_timeout"),
        ("rerank", "rerank", "rerank_request_timeout"),
        ("query_rewrite", "query_rewrite", "query_rewrite_timeout"),
    ],
)
def test_runtime_resolves_each_purpose(
    auth_client, auth_db, admin_actor, model_settings, kind, prefix, timeout_field
):
    profile = create_profile(auth_client, kind)
    activate_profile(auth_client, profile)
    effective = resolve(auth_db, model_settings)
    assert getattr(effective, f"{prefix}_api_base_url").rstrip("/") == "https://models.example/v1"
    assert getattr(effective, f"{prefix}_api_key") == MODEL_KEY
    assert getattr(effective, f"{prefix}_model") == f"test-{kind}"
    assert getattr(effective, timeout_field) == 12
    if kind != "rerank":
        assert getattr(effective, f"{prefix}_max_retries") == 1
    if kind == "embedding":
        assert effective.document_embedding_dimensions == 2560
    if kind in ("rerank", "query_rewrite"):
        assert getattr(effective, f"{prefix}_enabled") is True
    if kind != "chat":
        assert effective.chat_model == model_settings.chat_model
    assert model_settings.chat_api_key == "environment-chat-test-key"


# 验证切换后的新解析使用新配置，先前快照不会被原地修改，取消后恢复环境。
def test_new_resolution_changes_without_mutating_inflight_snapshot(
    auth_client, auth_db, admin_actor, model_settings
):
    first = create_profile(auth_client, model="chat-before")
    second = create_profile(auth_client, model="chat-after", api_key="after-test-secret")
    activate_profile(auth_client, first)
    inflight = resolve(auth_db, model_settings)
    activate_profile(auth_client, second)
    following = resolve(auth_db, model_settings)
    assert inflight.chat_model == "chat-before" and inflight.chat_api_key == MODEL_KEY
    assert following.chat_model == "chat-after" and following.chat_api_key == "after-test-secret"
    response = auth_client.post(f"/api/admin/models/{second['id']}/deactivate")
    assert response.status_code == 200, f"取消默认应成功：{response.text}"
    reverted = resolve(auth_db, model_settings)
    assert reverted.chat_model == "environment-chat"
    assert reverted.chat_api_key == "environment-chat-test-key"


# 验证有效配置的密钥不可解密时明确失败，不使用 .env 绕过已选择的后台默认。
def test_unreadable_secret_does_not_fall_back(auth_client, auth_db, admin_actor, model_settings):
    from app.core.errors import AppError

    profile = create_profile(auth_client)
    activate_profile(auth_client, profile)
    missing_key_settings = model_settings.model_copy(update={"model_config_encryption_key": ""})
    with pytest.raises(AppError) as caught:
        resolve(auth_db, missing_key_settings)
    assert caught.value.status_code == 503
    assert caught.value.code == "model_secret_unavailable"
    assert MODEL_KEY not in str(caught.value)
