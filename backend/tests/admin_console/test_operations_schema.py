"""管理改版首批 RED：持久化历史、配置版本及数据库关系保护。"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError

from app.models import base

NEW_TABLES = {"admin_audit_events", "model_probe_results"}
NOW = datetime(2026, 10, 22, 8, tzinfo=UTC)
FORBIDDEN_COLUMNS = {
    "password",
    "password_hash",
    "api_key",
    "api_key_encrypted",
    "token",
    "token_hash",
    "session_token",
    "request_body",
    "response_body",
    "storage_key",
    "original_filename",
    "query",
    "answer",
    "content",
    "embedding_vector",
}


def required_table(name):
    # 用业务断言说明缺失结构，避免尚未实现的新模块导致测试收集错误。
    assert name in base.metadata.tables, (
        f"后台运行历史无法持久化：metadata 缺少 {name}；"
        "应注册对应模型并由增量迁移创建，不能只把历史留在日志流。"
    )
    return base.metadata.tables[name]


@pytest.fixture
def operations_connection():
    # 每个测试使用启用外键的独立内存库，不连接实际业务数据库。
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    base.metadata.create_all(engine)
    try:
        with engine.begin() as connection:
            actor_id, profile_id = uuid4(), uuid4()
            connection.execute(
                base.metadata.tables["users"]
                .insert()
                .values(
                    id=actor_id,
                    display_name="结构测试管理员",
                    email="schema-admin@example.com",
                    role="admin",
                    status="active",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            connection.execute(
                base.metadata.tables["model_profiles"]
                .insert()
                .values(
                    id=profile_id,
                    name="固定测试配置",
                    kind="chat",
                    base_url="http://localhost:11434/v1",
                    model="schema-fixture",
                    enabled=True,
                    timeout_seconds=10,
                    max_retries=0,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            yield connection, actor_id, profile_id
    finally:
        engine.dispose()


def audit_values(actor_id, resource_id, **changes):
    return {
        "id": uuid4(),
        "actor_user_id": actor_id,
        "action": "model.update",
        "resource_type": "model",
        "resource_id": resource_id,
        "result": "success",
        "changes_json": {"secret_changed": True},
        "error_code": None,
        "trace_id": "0123456789abcdef",
        "created_at": NOW,
        **changes,
    }


def probe_values(actor_id, profile_id, **changes):
    return {
        "id": uuid4(),
        "profile_id": profile_id,
        "profile_revision": 1,
        "actor_user_id": actor_id,
        "status": "running",
        "code": None,
        "latency_ms": None,
        "started_at": NOW,
        "finished_at": None,
        "lease_expires_at": NOW + timedelta(seconds=20),
        "trace_id": "0123456789abcdef",
        **changes,
    }


# 验证 Alembic 统一 metadata 能发现新表，而非只在某个请求或测试中临时导入。
def test_operations_history_is_registered_for_migrations():
    missing = NEW_TABLES - base.metadata.tables.keys()
    assert not missing, f"缺少可迁移的后台历史模型：{sorted(missing)}；应从 models.base 注册。"


# 验证已有和新建配置都有起始版本，避免测试结果无法绑定确定的配置快照。
def test_profile_revision_is_non_nullable_and_defaults_to_one(operations_connection):
    connection, _actor_id, profile_id = operations_connection
    profiles = base.metadata.tables["model_profiles"]
    assert "revision" in profiles.c, "模型配置缺少 revision，无法判断诊断结果是否已经过期。"
    assert not profiles.c.revision.nullable, "配置版本必须非空，不能出现无法比对的历史配置。"
    revision = connection.execute(
        select(profiles.c.revision).where(profiles.c.id == profile_id)
    ).scalar_one()
    assert revision == 1, f"未指定版本的新配置应从 1 开始，实际为 {revision}。"


# 验证账号软删除、模型物理删除后仍可追溯原操作者与对象，不级联丢失审计。
def test_audit_history_survives_soft_deleted_actor_and_deleted_resource(operations_connection):
    connection, actor_id, profile_id = operations_connection
    audit = required_table("admin_audit_events")
    values = audit_values(actor_id, profile_id)
    connection.execute(audit.insert().values(**values))
    users, profiles = base.metadata.tables["users"], base.metadata.tables["model_profiles"]
    connection.execute(users.update().where(users.c.id == actor_id).values(deleted_at=NOW))
    connection.execute(profiles.delete().where(profiles.c.id == profile_id))
    saved = connection.execute(select(audit).where(audit.c.id == values["id"])).mappings().one()
    assert (saved["actor_user_id"], saved["resource_id"]) == (actor_id, profile_id), (
        "删除管理对象或软删除操作者后，审计必须保留原 UUID 以供追溯。"
    )
    assert saved["changes_json"] == {"secret_changed": True}


# 验证删除已测试配置只置空关联，保留测试版本、时间和结果用于诊断历史。
def test_deleting_profile_preserves_probe_with_original_revision(operations_connection):
    connection, actor_id, profile_id = operations_connection
    probes = required_table("model_probe_results")
    values = probe_values(actor_id, profile_id)
    connection.execute(probes.insert().values(**values))
    profiles = base.metadata.tables["model_profiles"]
    connection.execute(profiles.delete().where(profiles.c.id == profile_id))
    saved = connection.execute(select(probes).where(probes.c.id == values["id"])).mappings().one()
    assert saved["profile_id"] is None, "删除配置应 SET NULL，而不是阻止删除或级联删除历史。"
    assert saved["profile_revision"] == 1 and saved["status"] == "running", (
        "失去配置关联不能改写实际测试版本或伪造测试终态。"
    )


# 验证诊断结果能从在途更新为终态，且后续配置修改不会改写所测版本。
def test_probe_completion_retains_snapshot_after_profile_edit(operations_connection):
    connection, actor_id, profile_id = operations_connection
    probes = required_table("model_probe_results")
    profiles = base.metadata.tables["model_profiles"]
    assert "revision" in profiles.c, "模型配置缺少版本，无法验证测试期间配置变化。"
    values = probe_values(actor_id, profile_id)
    connection.execute(probes.insert().values(**values))
    connection.execute(profiles.update().where(profiles.c.id == profile_id).values(revision=2))
    connection.execute(
        probes.update()
        .where(probes.c.id == values["id"])
        .values(
            status="passed",
            code="model_test_passed",
            latency_ms=12,
            finished_at=NOW + timedelta(milliseconds=12),
        )
    )
    saved = connection.execute(select(probes).where(probes.c.id == values["id"])).mappings().one()
    assert (saved["profile_revision"], saved["status"], saved["latency_ms"]) == (1, "passed", 12)


# 验证成功、拒绝和失败以外的审计结果不能写入，防止查询及统计口径漂移。
@pytest.mark.parametrize("invalid_result", ["running", "unknown"])
def test_database_rejects_invalid_audit_result(operations_connection, invalid_result):
    connection, actor_id, profile_id = operations_connection
    audit = required_table("admin_audit_events")
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(
            audit.insert().values(**audit_values(actor_id, profile_id, result=invalid_result))
        )


# 验证在途及终态以外的诊断状态不能写入，强杀后的未知状态须按租约推导。
@pytest.mark.parametrize("invalid_status", ["success", "arbitrary-state"])
def test_database_rejects_invalid_probe_status(operations_connection, invalid_status):
    connection, actor_id, profile_id = operations_connection
    probes = required_table("model_probe_results")
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.execute(
            probes.insert().values(**probe_values(actor_id, profile_id, status=invalid_status))
        )


# 验证新增历史表不引入秘密或资料正文专用字段；JSON 白名单另由服务测试覆盖。
@pytest.mark.parametrize("table_name", sorted(NEW_TABLES))
def test_history_tables_have_no_secret_or_private_content_columns(table_name):
    table = required_table(table_name)
    leaked = FORBIDDEN_COLUMNS & set(table.c.keys())
    assert not leaked, f"{table_name} 出现禁止持久化的秘密或资料字段：{sorted(leaked)}。"


# 验证时间、操作者、动作、trace ID 查询与诊断租约检查都有对应索引。
def test_history_indexes_and_timezone_columns_support_queries():
    audit, probes = required_table("admin_audit_events"), required_table("model_probe_results")
    audit_indexes = {tuple(column.name for column in index.columns) for index in audit.indexes}
    assert {
        ("created_at", "id"),
        ("actor_user_id", "created_at"),
        ("action", "created_at"),
        ("trace_id",),
    } <= audit_indexes
    probe_indexes = {tuple(column.name for column in index.columns) for index in probes.indexes}
    assert ("profile_id", "started_at") in probe_indexes
    assert any(columns[0] == "lease_expires_at" for columns in probe_indexes)
    for table, names in (
        (audit, ("created_at",)),
        (probes, ("started_at", "finished_at", "lease_expires_at")),
    ):
        for name in names:
            assert table.c[name].type.timezone, f"{table.name}.{name} 应保留 UTC 时区语义。"
