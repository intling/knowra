"""请求内模型诊断：固定协议、失败分类、准入、清理及安全投影。"""

import asyncio
import importlib
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlmodel import select

from app.main import app
from app.models.admin_operations import AdminAuditEvent, ModelProbeResult
from app.models.model_configuration import ModelBinding
from tests.admin_console.helpers import assert_error, assert_status, create_profile
from tests.auth_helpers import make_account


def fake_client(monkeypatch, handler):
    # 使用真实异步 HTTPX 和替换传输执行协议，不调用付费模型。
    actual = httpx.AsyncClient
    clients = []

    def factory(**kwargs):
        assert kwargs.get("follow_redirects") is False, "诊断不能跟随重定向"
        client = actual(**(kwargs | {"transport": httpx.MockTransport(handler)}))
        clients.append(client)
        return client

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return clients


def response_for(kind):
    if kind == "embedding":
        return {"data": [{"embedding": [0.01] * 2560}]}
    if kind == "rerank":
        return {
            "results": [{"index": 0, "relevance_score": 0.9}, {"index": 1, "relevance_score": 0.1}]
        }
    return {"choices": [{"message": {"content": "OK"}}]}


# 验证四用途只发送固定短样例，禁用配置也可测试，不持数据库事务等待网络且不切换默认。
@pytest.mark.parametrize("kind", ["chat", "query_rewrite", "embedding", "rerank"])
def test_explicit_probe_protocol_and_atomic_result(
    auth_client, auth_db, admin_actor, model_settings, monkeypatch, kind
):
    profile = create_profile(auth_client, kind, enabled=False)
    requests = []

    def handler(request):
        assert not auth_db.in_transaction(), "网络调用不能持数据库事务"
        requests.append(request)
        return httpx.Response(200, json=response_for(kind))

    clients = fake_client(monkeypatch, handler)
    body = assert_status(
        auth_client.post(f"/api/admin/models/{profile['id']}/test", json={"expected_revision": 1}),
        200,
        "显式诊断应返回有界结果",
    )
    assert body["status"] == "passed" and body["code"] == "model_test_passed" and body["is_current"]
    assert len(requests) == 1 and clients[0].is_closed, "无重试且客户端必须关闭"
    payload = json.loads(requests[0].content)
    assert payload["model"] == profile["model"]
    if kind in {"chat", "query_rewrite"}:
        assert payload["stream"] is False and payload["max_tokens"] <= 32
    if kind == "embedding":
        assert payload["dimensions"] == 2560
    binding = auth_db.get(ModelBinding, kind)
    assert binding is None or binding.profile_id is None, "测试不能激活配置"
    rows = auth_db.exec(select(ModelProbeResult)).all()
    assert len(rows) == 1 and rows[0].status == "passed"
    events = auth_db.exec(
        select(AdminAuditEvent).where(AdminAuditEvent.action == "model.test")
    ).all()
    assert len(events) == 1 and events[0].result == "success"
    assert set(events[0].changes_json) == {"profile_revision", "status", "code", "latency_ms"}
    assert "console-model-secret" not in json.dumps(body), "诊断不能回显密钥或输出内容"


# 验证上游鉴权、网络、格式、重定向及异常响应以固定安全码返回，响应原文不得外泄。
@pytest.mark.parametrize(
    "failure,code",
    [
        ("auth", "model_test_auth_failed"),
        ("connect", "model_test_unreachable"),
        ("timeout", "model_test_timeout"),
        ("invalid", "model_test_invalid_response"),
        ("redirect", "model_test_failed"),
        ("server", "model_test_failed"),
    ],
)
def test_probe_safe_failure_categories(
    auth_client, auth_db, admin_actor, model_settings, monkeypatch, failure, code
):
    profile = create_profile(auth_client)
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "connect":
            raise httpx.ConnectError("PRIVATE upstream secret", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("PRIVATE response", request=request)
        status = {"auth": 401, "invalid": 200, "redirect": 302, "server": 500}[failure]
        return httpx.Response(
            status, json={"private": "PRIVATE"}, headers={"Location": "http://169.254.169.254/"}
        )

    clients = fake_client(monkeypatch, handler)
    body = assert_status(
        auth_client.post(f"/api/admin/models/{profile['id']}/test", json={"expected_revision": 1}),
        200,
        "已执行的诊断失败仍返回安全结果",
    )
    assert body["status"] == "failed" and body["code"] == code
    assert "PRIVATE" not in json.dumps(body)
    assert len(calls) == 1 and clients[0].is_closed


# 验证 Embedding 维度与重排索引结构，不将 HTTP 200 等同于协议通过。
@pytest.mark.parametrize(
    "kind,payload",
    [
        ("embedding", {"data": [{"embedding": [1, 2]}]}),
        ("embedding", {"data": [{"embedding": ["bad"] * 2560}]}),
        ("rerank", {"results": [{"index": 99, "relevance_score": 1}]}),
        ("rerank", {"results": []}),
    ],
)
def test_probe_validates_output(
    auth_client, admin_actor, model_settings, monkeypatch, kind, payload
):
    profile = create_profile(auth_client, kind)
    fake_client(monkeypatch, lambda _: httpx.Response(200, json=payload))
    body = assert_status(
        auth_client.post(f"/api/admin/models/{profile['id']}/test", json={"expected_revision": 1}),
        200,
        "须验证用途协议",
    )
    assert body["code"] == "model_test_invalid_response"


# 验证版本、秘密与任意输入校验发生在网络调用之前。
@pytest.mark.parametrize(
    "case,status,code",
    [
        ("version", 409, "model_revision_conflict"),
        ("key", 503, "model_secret_unavailable"),
        ("extra", 422, None),
    ],
)
def test_probe_admission_rejects_before_network(
    auth_client, auth_db, admin_actor, model_settings, monkeypatch, case, status, code
):
    profile = create_profile(auth_client)
    if case == "key":
        model_settings.model_config_encryption_key = ""
    payload = {"expected_revision": 2 if case == "version" else 1}
    if case == "extra":
        payload["api_key"] = "SECRET-INPUT"
    calls = []
    fake_client(monkeypatch, lambda req: calls.append(req))
    result = assert_status(
        auth_client.post(f"/api/admin/models/{profile['id']}/test", json=payload),
        status,
        "无效请求不得启动诊断",
    )
    if code:
        assert result["code"] == code
    assert "SECRET-INPUT" not in json.dumps(result) and not calls
    assert not auth_db.exec(select(ModelProbeResult)).all(), "未执行不得伪造测试结果"


# 验证重复测试在服务端限流，有正数 Retry-After；过期运行租约不能永久占用并发。
def test_probe_cooldown_and_expired_lease(
    auth_client, auth_db, admin_actor, model_settings, monkeypatch
):
    first = create_profile(auth_client)
    fake_client(monkeypatch, lambda _: httpx.Response(200, json=response_for("chat")))
    assert_status(
        auth_client.post(f"/api/admin/models/{first['id']}/test", json={"expected_revision": 1}),
        200,
        "首次诊断",
    )
    response = auth_client.post(
        f"/api/admin/models/{first['id']}/test", json={"expected_revision": 1}
    )
    assert_error(response, 429, "model_test_rate_limited", "重复诊断应冷却")
    assert int(response.headers["Retry-After"]) > 0
    from uuid import UUID

    second = create_profile(auth_client)
    for _ in range(3):
        auth_db.add(
            ModelProbeResult(
                profile_id=UUID(first["id"]),
                profile_revision=1,
                actor_user_id=admin_actor.id,
                status="running",
                started_at=datetime.now(UTC) - timedelta(minutes=2),
                lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
                trace_id="expired",
            )
        )
    auth_db.commit()
    assert_status(
        auth_client.post(f"/api/admin/models/{second['id']}/test", json={"expected_revision": 1}),
        200,
        "到期租约不能占用名额",
    )


# 验证应用开始关闭时拒绝新测试，不创建外部客户端。
def test_probe_shutdown_rejects_admission(auth_client, admin_actor, model_settings):
    profile = create_profile(auth_client)
    state = app.state.application_shutdown_state
    state.is_shutting_down = True
    try:
        assert_error(
            auth_client.post(
                f"/api/admin/models/{profile['id']}/test", json={"expected_revision": 1}
            ),
            503,
            "admin_dependency_unavailable",
            "关闭期间不接受新诊断",
        )
    finally:
        state.is_shutting_down = False


# 验证总截止时间可取消慢响应，并在 finally 关闭客户端、写入终态。
def test_probe_total_timeout_cancels_transport(
    auth_client, auth_db, admin_actor, model_settings, monkeypatch
):
    profile = create_profile(auth_client)
    model_settings.admin_model_test_timeout_seconds = 0.03

    async def slow(_):
        await asyncio.sleep(1)
        return httpx.Response(200, json=response_for("chat"))

    clients = fake_client(monkeypatch, slow)
    body = assert_status(
        auth_client.post(f"/api/admin/models/{profile['id']}/test", json={"expected_revision": 1}),
        200,
        "总截止时间应覆盖整个网络调用",
    )
    assert body["code"] == "model_test_timeout" and clients[0].is_closed
    assert auth_db.exec(select(ModelProbeResult)).one().status == "failed"


# 验证诊断期间编辑或删除配置后结果仍关联旧版本，不被标为当前可用。
@pytest.mark.parametrize("change", ["edit", "delete"])
def test_probe_config_change_during_network_is_stale(
    auth_client, auth_db, admin_actor, model_settings, monkeypatch, change
):
    from uuid import UUID

    from app.models.model_configuration import ModelProfile

    profile = create_profile(auth_client)

    def handler(_):
        row = auth_db.get(ModelProfile, UUID(profile["id"]))
        if change == "edit":
            row.revision += 1
            auth_db.add(row)
        else:
            auth_db.delete(row)
        auth_db.commit()
        return httpx.Response(200, json=response_for("chat"))

    fake_client(monkeypatch, handler)
    body = assert_status(
        auth_client.post(f"/api/admin/models/{profile['id']}/test", json={"expected_revision": 1}),
        200,
        "旧版本诊断可保存但不能代表当前配置",
    )
    assert body["config_revision"] == 1 and body["is_current"] is False


# 验证跨 worker 名额使用数据库 running 租约计数，而非进程内信号量。
def test_probe_database_lease_enforces_global_limit(
    auth_client, auth_db, admin_actor, model_settings
):
    profile = create_profile(auth_client)
    other = make_account(auth_db, role="admin")
    for _ in range(2):
        auth_db.add(
            ModelProbeResult(
                profile_revision=1,
                actor_user_id=other.id,
                lease_expires_at=datetime.now(UTC) + timedelta(seconds=20),
                trace_id="other-worker",
            )
        )
    auth_db.commit()
    result = auth_client.post(
        f"/api/admin/models/{profile['id']}/test", json={"expected_revision": 1}
    )
    assert_error(result, 429, "model_test_rate_limited", "其他 worker 的有效租约也应占用名额")


# 验证完成事务审计失败时不能留下 passed 结果，清理后不再占用运行名额。
def test_probe_result_audit_failure_is_atomic(
    auth_client, auth_db, admin_actor, model_settings, monkeypatch
):
    from tests.admin_console.test_audit_transactions import reject_audit_inserts

    profile = create_profile(auth_client)
    clients = fake_client(monkeypatch, lambda _: httpx.Response(200, json=response_for("chat")))
    with reject_audit_inserts(auth_db):
        assert_error(
            auth_client.post(
                f"/api/admin/models/{profile['id']}/test", json={"expected_revision": 1}
            ),
            503,
            "admin_audit_unavailable",
            "结果与成功审计必须同事务",
        )
    assert clients[0].is_closed
    row = auth_db.exec(select(ModelProbeResult)).one()
    assert row.status == "interrupted", "审计故障不可持久化未经审计的通过结果"


# 验证请求取消触发 finally 关闭客户端，并保留安全中断终态。
@pytest.mark.asyncio
async def test_probe_cancel_cleans_client_and_lease(
    auth_db, admin_actor, model_settings, monkeypatch
):
    service = importlib.import_module("app.services.model_probes")
    from app.schemas.model_configuration import ModelCreate
    from app.services.model_configuration import create_profile as create
    from tests.admin_console.helpers import profile_payload

    profile = create(auth_db, admin_actor, ModelCreate(**profile_payload()), model_settings)
    started = asyncio.Event()

    async def handler(_):
        started.set()
        await asyncio.sleep(10)

    clients = fake_client(monkeypatch, handler)
    task = asyncio.create_task(
        service.run_probe(
            auth_db,
            admin_actor,
            profile.id,
            1,
            model_settings,
            app.state.application_shutdown_state,
        )
    )
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert clients[0].is_closed
    assert auth_db.exec(select(ModelProbeResult)).one().status == "interrupted"
    assert (
        auth_db.exec(select(AdminAuditEvent).where(AdminAuditEvent.action == "model.test"))
        .one()
        .changes_json["status"]
        == "interrupted"
    )


# 验证重排原生协议路径与已有适配器一致，并拒绝不完整或越界分数。
@pytest.mark.parametrize(
    "native,rows,passed",
    [
        (True, [{"index": 0, "relevance_score": 0.9}, {"index": 1, "relevance_score": 0.1}], True),
        (False, [{"index": 0, "relevance_score": 0.9}], False),
        (False, [{"index": 0, "relevance_score": 9}, {"index": 1, "relevance_score": 0.1}], False),
    ],
)
def test_rerank_protocol_matches_production_adapter(
    auth_client, admin_actor, model_settings, monkeypatch, native, rows, passed
):
    profile = create_profile(
        auth_client, "rerank", api_format="dashscope" if native else "compatible"
    )

    def handler(request):
        if native:
            assert request.url.path.endswith("/services/rerank/text-rerank/text-rerank"), (
                "原生重排路径应与生产协议一致"
            )
        return httpx.Response(
            200, json={"output": {"results": rows}} if native else {"results": rows}
        )

    fake_client(monkeypatch, handler)
    body = assert_status(
        auth_client.post(f"/api/admin/models/{profile['id']}/test", json={"expected_revision": 1}),
        200,
        "按真实重排协议诊断",
    )
    assert body["status"] == ("passed" if passed else "failed")


# 验证无鉴权本地模型不发送空 Bearer；真实 HTTP 传输会拒绝带尾空格的空鉴权头。
def test_local_model_without_key_omits_authorization(
    auth_client, admin_actor, model_settings, monkeypatch
):
    profile = create_profile(auth_client, api_key="")
    headers = []

    def handler(request):
        headers.append(dict(request.headers))
        return httpx.Response(200, json=response_for("chat"))

    fake_client(monkeypatch, handler)
    body = assert_status(
        auth_client.post(f"/api/admin/models/{profile['id']}/test", json={"expected_revision": 1}),
        200,
        "无鉴权模型也应可显式测试",
    )
    assert body["status"] == "passed"
    assert "authorization" not in headers[0], "无密钥应省略鉴权头，不能发送空 Bearer"
