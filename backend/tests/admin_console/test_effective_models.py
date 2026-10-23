"""模型配置版本与四用途生效来源。"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.models.admin_operations import ModelProbeResult
from app.models.model_configuration import ModelBinding
from tests.admin_console.helpers import activate_profile, assert_status, create_profile
from tests.auth_helpers import login_as, make_account


# 验证四用途在环境回退时准确区分开启和关闭，响应不包含环境秘密。
def test_effective_environment_sources(auth_client, admin_actor, model_settings):
    rows = assert_status(auth_client.get("/api/admin/models/effective"), 200, "应有四用途生效摘要")
    assert {r["kind"] for r in rows} == {"chat", "embedding", "rerank", "query_rewrite"}
    assert all(r["source"] == "environment" and r["profile_id"] is None for r in rows)
    assert {r["kind"]: r["enabled"] for r in rows} == {
        "chat": True,
        "embedding": True,
        "rerank": False,
        "query_rewrite": False,
    }
    assert "environment-chat-test-key" not in json.dumps(rows)
    assert all(r["latest_probe"] is None for r in rows)


# 验证配置修订号逐次编辑递增，切换默认只增加绑定版本，两种版本互不混淆。
@pytest.mark.parametrize("kind", ["chat", "embedding", "rerank", "query_rewrite"])
def test_profile_and_binding_versions_are_distinct(
    auth_client, auth_db, admin_actor, model_settings, kind
):
    first = create_profile(auth_client, kind)
    assert first.get("revision") == 1, "配置公开响应应新增修订号"
    second = create_profile(auth_client, kind)
    activate_profile(auth_client, first)
    updated = assert_status(
        auth_client.patch(f"/api/admin/models/{first['id']}", json={"name": "新的名称"}),
        200,
        "编辑应递增配置版本",
    )
    assert updated["revision"] == 2
    rows = assert_status(auth_client.get("/api/admin/models/effective"), 200, "应返回生效配置")
    effective = next(r for r in rows if r["kind"] == kind)
    assert effective["source"] == "profile" and effective["profile_id"] == first["id"]
    assert effective["profile_revision"] == 2 and effective["binding_revision"] == 2
    assert effective["model"] == first["model"] and effective["enabled"]
    assert second["id"] not in json.dumps(rows), "非默认配置不应伪装为当前生效"
    assert_status(auth_client.post(f"/api/admin/models/{first['id']}/deactivate"), 200, "恢复环境")
    assert auth_db.get(ModelBinding, kind).revision == 3


# 验证诊断参考必须同时满足配置版本和 15 分钟时效，租约到期不能冒充成功。
@pytest.mark.parametrize(
    "revision,age,status,current",
    [
        (1, 1, "passed", True),
        (2, 1, "passed", False),
        (1, 16, "passed", False),
        (1, 1, "running", False),
    ],
)
def test_effective_probe_freshness(
    auth_client, auth_db, admin_actor, model_settings, revision, age, status, current
):
    from uuid import UUID

    profile = create_profile(auth_client)
    activate_profile(auth_client, profile)
    now = datetime.now(UTC)
    auth_db.add(
        ModelProbeResult(
            profile_id=UUID(profile["id"]),
            profile_revision=revision,
            actor_user_id=admin_actor.id,
            status=status,
            code="model_test_passed" if status == "passed" else None,
            started_at=now - timedelta(minutes=age),
            finished_at=now - timedelta(minutes=age) if status == "passed" else None,
            lease_expires_at=now - timedelta(seconds=1),
            trace_id="probe-freshness",
        )
    )
    auth_db.commit()
    effective = assert_status(
        auth_client.get("/api/admin/models/effective"), 200, "应包含最新诊断摘要"
    )[0]
    probe = effective["latest_probe"]
    assert probe["is_current"] is current
    assert probe["status"] == ("interrupted" if status == "running" else status)
    assert "raw_response" not in probe


# 验证非管理员无法调用新的生效接口。
@pytest.mark.parametrize("role", [None, "member", "viewer"])
def test_effective_requires_model_permission(auth_client, auth_db, role):
    if role:
        login_as(auth_client, auth_db, make_account(auth_db, role=role))
    else:
        auth_client.cookies.clear()
    assert_status(
        auth_client.get("/api/admin/models/effective"),
        403 if role else 401,
        "生效配置必须要求管理员",
    )
