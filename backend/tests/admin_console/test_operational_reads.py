"""管理员只读运行投影：权限、UTC 窗口、关联、统计与审计白名单。"""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlmodel import select

from app.models.admin_operations import AdminAuditEvent
from app.models.document_chunking import DocumentChunkJob
from app.models.document_embedding import DocumentEmbeddingJob
from app.models.document_parsing import DocumentParseJob
from tests.admin_console.helpers import assert_error, assert_status
from tests.auth_helpers import login_as, make_account, seed_knowledge_chain


# 验证新增两项固定权限只授予管理员，不能通过客户端 owner 或 role 提权。
@pytest.mark.parametrize("role", ["admin", "member", "viewer", None])
@pytest.mark.parametrize(
    "path",
    [
        "/api/admin/overview",
        "/api/admin/jobs",
        "/api/admin/system/status",
        "/api/admin/audit-events",
    ],
)
def test_operations_permissions(auth_client, auth_db, model_settings, role, path):
    if role:
        login_as(auth_client, auth_db, make_account(auth_db, role=role))
    else:
        auth_client.cookies.clear()
    response = auth_client.get(path, params={"role": "admin", "owner_user_id": str(uuid4())})
    assert_status(
        response, 200 if role == "admin" else 403 if role else 401, "运行数据仅允许真实管理员读取"
    )
    if role == "admin":
        me = auth_client.get("/api/users/me").json()
        assert {"operations:read", "audit:read"} <= set(me["permissions"])


@pytest.fixture
def job_chain(auth_db, tmp_path):
    target = make_account(auth_db)
    upload, parsed, chunk, chunks, _ = seed_knowledge_chain(auth_db, tmp_path, target, vectors=1)
    parse = auth_db.get(DocumentParseJob, parsed.parse_job_id)
    embed = auth_db.exec(
        select(DocumentEmbeddingJob).where(DocumentEmbeddingJob.chunk_job_id == chunk.id)
    ).one()
    now = datetime.now(UTC)
    for i, row in enumerate([parse, chunk, embed]):
        row.created_at = now - timedelta(minutes=3 - i)
        row.started_at = row.created_at
        row.finished_at = now - timedelta(minutes=1)
        row.status = "failed" if i == 1 else "succeeded"
        row.error_code = "PRIVATE arbitrary failure code" if i == 1 else None
        row.error_message = "PRIVATE /storage/secret.pdf raw answer"
        auth_db.add(row)
    auth_db.commit()
    return target, upload, parsed, [parse, chunk, embed], chunks


# 验证三表全量分页、阶段筛选与安全投影，原错误、资料名与正文不出现在结果中。
def test_jobs_union_filter_pagination_and_safe_projection(
    auth_client, auth_db, admin_actor, job_chain
):
    target, upload, parsed, jobs, chunks = job_chain
    body = assert_status(
        auth_client.get("/api/admin/jobs", params={"limit": 2}), 200, "统一任务列表应支持三阶段"
    )
    assert body["total"] == 3 and len(body["items"]) == 2
    assert [i["kind"] for i in body["items"]] == ["embedding", "chunk"]
    filtered = assert_status(
        auth_client.get(
            "/api/admin/jobs",
            params={"kind": "chunk", "status": "failed", "owner_user_id": str(target.id)},
        ),
        200,
        "组合筛选作用于全量",
    )
    assert filtered["total"] == 1
    item = filtered["items"][0]
    assert item["uploaded_file_id"] == str(upload.id) and item["error_code"] == "processing_failed"
    assert item["duration_ms"] >= 0 and item["owner_user_id"] == str(target.id)
    all_text = json.dumps(body, ensure_ascii=False) + json.dumps(filtered, ensure_ascii=False)
    for private in [
        "PRIVATE",
        upload.original_filename,
        upload.storage_key,
        chunks[0].text,
        chunks[0].contextualized_text,
    ]:
        assert private not in all_text, "运行端点不得泄露资料或原始错误"
    assert auth_client.get("/api/parsed-documents").json() == [], "管理员不得借任务读取其他账号正文"


# 验证详情使用上传/解析真实关系，保留多次任务尝试，不把同账号其他资料拼入时间线。
def test_job_detail_tracks_actual_attempts_and_missing_stage(
    auth_client, auth_db, admin_actor, job_chain, tmp_path
):
    target, upload, parsed, jobs, _ = job_chain
    other = seed_knowledge_chain(auth_db, tmp_path, target, vectors=1)
    extra = DocumentChunkJob(parsed_document_id=parsed.id, owner_user_id=target.id, status="queued")
    auth_db.add(extra)
    auth_db.delete(jobs[2])
    auth_db.commit()
    body = assert_status(
        auth_client.get(f"/api/admin/jobs/chunk/{jobs[1].id}"),
        200,
        "任务详情应关联实际上传所有尝试",
    )
    assert body["job"]["id"] == str(jobs[1].id)
    assert len(body["timeline"]) == 3
    assert {i["uploaded_file_id"] for i in body["timeline"]} == {str(upload.id)}
    assert set(body["missing_kinds"]) == {"embedding"}
    assert str(other[0].id) not in json.dumps(body)
    target.deleted_at = datetime.now(UTC)
    auth_db.add(target)
    auth_db.commit()
    page = assert_status(
        auth_client.get("/api/admin/jobs", params={"owner_user_id": str(target.id)}),
        200,
        "历史任务应保留",
    )
    assert all(i["owner_label"] == "已删除账号" for i in page["items"])


# 验证任务 UTC 半开区间与错误参数，不能静默忽略错误过滤条件。
@pytest.mark.parametrize(
    "params",
    [
        {"kind": "unknown"},
        {"status": "done"},
        {"owner_user_id": "wrong"},
        {"limit": 101},
        {"offset": -1},
        {"from": "2026-10-22T00:00:00Z", "to": "2026-10-21T00:00:00Z"},
        {"from": "2026-01-01T00:00:00Z", "to": "2026-10-22T00:00:00Z"},
        {"from": "bad"},
    ],
)
def test_jobs_validate_filters(auth_client, admin_actor, params):
    assert_status(
        auth_client.get("/api/admin/jobs", params=params), 422, "任务查询需明确拒绝非法条件"
    )


# 验证创建时间等于 from 被包含，等于 to 被排除，找不到任务返回业务原因。
def test_jobs_utc_boundaries_and_missing(auth_client, auth_db, admin_actor, job_chain):
    row = job_chain[3][0]
    timestamp = row.created_at.replace(tzinfo=UTC)
    body = assert_status(
        auth_client.get(
            "/api/admin/jobs",
            params={
                "kind": "parse",
                "from": timestamp.isoformat(),
                "to": (timestamp + timedelta(seconds=1)).isoformat(),
            },
        ),
        200,
        "任务时间应使用半开区间",
    )
    assert body["total"] == 1
    body = auth_client.get(
        "/api/admin/jobs",
        params={
            "kind": "parse",
            "from": (timestamp - timedelta(seconds=1)).isoformat(),
            "to": timestamp.isoformat(),
        },
    ).json()
    assert body["total"] == 0
    assert_error(
        auth_client.get(f"/api/admin/jobs/parse/{uuid4()}"),
        404,
        "admin_job_not_found",
        "不存在任务需明确说明",
    )


# 验证总览排除软删除资料/账号，容量仅为原文件字节数，阶段结果按完成时间计算。
def test_overview_counts_and_finished_window(
    auth_client, auth_db, admin_actor, job_chain, tmp_path
):
    target, upload, parsed, jobs, _ = job_chain
    deleted = make_account(auth_db, deleted=True)
    seed_knowledge_chain(auth_db, tmp_path, deleted, vectors=1)
    another = seed_knowledge_chain(auth_db, tmp_path, target, vectors=1)
    another[0].deleted_at = datetime.now(UTC)
    auth_db.add(another[0])
    jobs[0].created_at = datetime.now(UTC) - timedelta(days=3)
    jobs[0].finished_at = datetime.now(UTC) - timedelta(minutes=5)
    auth_db.add(jobs[0])
    auth_db.commit()
    body = assert_status(auth_client.get("/api/admin/overview"), 200, "总览应聚合真实有效记录")
    assert body["users"]["total"] == 2
    assert body["uploads"]["total"] == 1 and body["uploads"]["logical_bytes"] == upload.byte_size
    parse = next(i for i in body["jobs_by_kind"] if i["kind"] == "parse")
    assert parse["succeeded_24h"] == 1, "最近完成必须按 finished_at 而非创建时间"
    assert "snapshot_at" in body and body["attention_items"]


# 验证无任务成功率为 null；统计区块故障保留其他区块并明确 null，不能伪装成零。
def test_overview_zero_denominator_and_partial_failure(auth_client, admin_actor, monkeypatch):
    import importlib

    service = importlib.import_module("app.services.admin_operations")
    body = assert_status(auth_client.get("/api/admin/overview"), 200, "空总览应可用")
    assert all(i["success_rate_24h"] is None for i in body["jobs_by_kind"])

    def fail(*args, **kwargs):
        raise RuntimeError("PRIVATE database detail")

    monkeypatch.setattr(service, "upload_totals", fail)
    body = assert_status(auth_client.get("/api/admin/overview"), 200, "局部故障不阻止其他统计")
    assert body["uploads"]["status"] == "unavailable" and body["uploads"]["total"] is None
    assert body["users"]["total"] == 1 and "PRIVATE" not in json.dumps(body)


# 验证系统状态使用当前实例范围并保留未知/禁用语义，刷新不会发起模型调用。
def test_system_status_scope_and_no_model_calls(auth_client, admin_actor, monkeypatch):
    import httpx

    def forbidden(*args, **kwargs):
        pytest.fail("读取状态不能调用外部模型")

    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    body = assert_status(auth_client.get("/api/admin/system/status"), 200, "系统状态应返回依赖检查")
    assert body["scope"] == "instance" and body["instance_id"] and body["checked_at"]
    components = {i["name"]: i for i in body["components"]}
    assert components["database"]["status"] == "ok"
    assert components["pgvector"]["status"] == "unknown", "SQLite 测试环境不能假装有 pgvector"
    assert components["document_models"]["status"] in {
        "unknown",
        "disabled",
        "ok",
        "degraded",
        "unavailable",
    }


# 验证认证依赖失败保持认证边界并返回安全 503，禁止匿名诊断旁路。
def test_operations_auth_dependency_outage(auth_client, admin_actor, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from app.api import deps

    def fail(*args):
        raise OperationalError("PRIVATE DSN", {}, Exception("PRIVATE"))

    monkeypatch.setattr(deps, "resolve_session_user", fail)
    body = assert_error(
        auth_client.get("/api/admin/system/status"),
        503,
        "admin_dependency_unavailable",
        "认证依赖失效应安全报告",
    )
    assert "PRIVATE" not in json.dumps(body)


# 验证审计组合筛选、稳定分页与脱敏投影，删除对象后历史仍可读取。
def test_audit_query_filters_history_and_whitelist(auth_client, auth_db, admin_actor):
    target = make_account(auth_db, deleted=True)
    now = datetime.now(UTC)
    events = [
        AdminAuditEvent(
            actor_user_id=admin_actor.id,
            action="user.update",
            resource_type="user",
            resource_id=target.id,
            result=result,
            trace_id=f"filter-{index}",
            created_at=now - timedelta(minutes=index),
            changes_json={
                "role": {"before": "member", "after": "viewer"},
                "password": "PRIVATE SECRET",
                "display_name": "PRIVATE NAME",
            },
        )
        for index, result in enumerate(["success", "denied", "failed"])
    ]
    auth_db.add_all(events)
    auth_db.commit()
    body = assert_status(
        auth_client.get(
            "/api/admin/audit-events",
            params={
                "limit": 1,
                "offset": 1,
                "action": "user.update",
                "actor_user_id": str(admin_actor.id),
            },
        ),
        200,
        "审计应全量筛选并稳定分页",
    )
    assert body["total"] == 3 and body["items"][0]["id"] == str(events[1].id)
    assert "PRIVATE" not in json.dumps(body)
    filtered = auth_client.get(
        "/api/admin/audit-events", params={"result": "success", "trace_id": "filter-0"}
    ).json()
    assert filtered["total"] == 1 and filtered["items"][0]["resource_id"] == str(target.id)
    assert filtered["items"][0]["changes_json"] == {"role": {"before": "member", "after": "viewer"}}
    assert_status(
        auth_client.delete(f"/api/admin/audit-events/{events[0].id}"), 404, "不提供修改删除台账入口"
    )


# 验证审计窗口、枚举与分页严格校验，无匹配或默认窗口之外返回空页。
@pytest.mark.parametrize(
    "params",
    [
        {"action": "user.export"},
        {"result": "unknown"},
        {"actor_user_id": "wrong"},
        {"limit": 101},
        {"from": "2026-10-22T00:00:00Z", "to": "2026-10-21T00:00:00Z"},
        {"from": "2026-01-01T00:00:00Z", "to": "2026-10-22T00:00:00Z"},
    ],
)
def test_audit_invalid_queries(auth_client, admin_actor, params):
    assert_status(
        auth_client.get("/api/admin/audit-events", params=params), 422, "非法审计查询应有原因"
    )


# 验证局部检查超时在预算内返回不可用，其余 readiness 区块仍可展示。
@pytest.mark.asyncio
async def test_system_checks_are_bounded_and_partial(auth_db, model_settings, monkeypatch):
    import asyncio
    from time import monotonic
    from types import SimpleNamespace

    from app.services import admin_system

    async def slow(*args):
        await asyncio.sleep(10)

    monkeypatch.setattr(admin_system, "database_check", slow)
    start = monotonic()
    body = await admin_system.system_status(
        auth_db,
        model_settings,
        SimpleNamespace(status="ready"),
        SimpleNamespace(is_shutting_down=False),
        "bounded-test",
    )
    assert monotonic() - start < 5, "系统主动检查必须有总截止时间"
    assert [c.status for c in body.components[:2]] == ["unavailable", "unavailable"]
    assert body.components[2].status == "ok"


# 验证系统主动检查不混入未受截止时间约束的同步配置查询；外部模型状态单独参考显式测试。
def test_system_active_checks_keep_external_models_unknown(auth_client, admin_actor):
    body = assert_status(
        auth_client.get("/api/admin/system/status"), 200, "有界主动检查应独立于模型摘要"
    )
    component = next((c for c in body["components"] if c["name"] == "external_models"), None)
    assert component is not None and component["status"] == "unknown", (
        "外部模型不得通过本地配置读取冒充已检查"
    )
