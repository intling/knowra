"""管理改版 RED：真实执行增量迁移，并保留账号、额度、私有资料和向量。"""

from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, MetaData, create_engine, event, inspect, text
from sqlmodel import Session

from app.models import base
from app.models.chat_quota import ChatUsage, UserChatLimit
from tests.auth_helpers import issue_session_token, make_account, seed_knowledge_chain

BASELINE_REVISION = "20261022_0001"
NEW_TABLES = {"admin_audit_events", "model_probe_results"}


def operations_revision():
    # 从真实迁移图寻找唯一新 head，不约束新迁移文件名或 revision 命名。
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[2] / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    heads = scripts.get_heads()
    assert len(heads) == 1, f"后台增量迁移必须保持唯一 head，实际为 {heads}。"
    assert heads[0] != BASELINE_REVISION, (
        "尚未提供后台改版增量迁移：当前仍停在模型配置迁移；"
        "应新增审计/诊断表及配置 revision，不能只用 metadata.create_all。"
    )
    revision = scripts.get_revision(heads[0])
    assert revision.down_revision == BASELINE_REVISION, (
        f"新迁移应接在当前基线 {BASELINE_REVISION} 后，实际为 {revision.down_revision}。"
    )
    return revision.module


def legacy_metadata():
    # 从旧业务结构构建升级前数据库副本，排除新表和新版本列，不修改全局 metadata。
    legacy = MetaData()
    for table in base.metadata.sorted_tables:
        if table.name not in NEW_TABLES:
            table.to_metadata(legacy)
    profiles = legacy.tables["model_profiles"]
    if "revision" in profiles.c:
        profiles._columns.remove(profiles.c.revision)
    for constraint in list(profiles.constraints):
        if isinstance(constraint, CheckConstraint) and "revision" in str(constraint.sqltext):
            profiles.constraints.remove(constraint)
    return legacy


def snapshot_legacy_rows(connection, metadata):
    # 使用原列集合及原始 SQL 值比较，避免升级后新增列或向量 ndarray 干扰数据相等性。
    snapshots = {}
    for table in metadata.sorted_tables:
        columns = ", ".join(f'"{column.name}"' for column in table.columns)
        ordering = ", ".join(f'"{column.name}"' for column in table.primary_key)
        snapshots[table.name] = connection.execute(
            text(f'SELECT {columns} FROM "{table.name}" ORDER BY {ordering}')
        ).all()
    return snapshots


@contextmanager
def seeded_legacy_database(tmp_path):
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    legacy = legacy_metadata()
    legacy.create_all(engine)
    try:
        with Session(engine) as session:
            user = make_account(session, email="migration-admin@example.com", role="admin")
            issue_session_token(session, user)
            session.add(UserChatLimit(user_id=user.id, hourly_limit=3))
            session.add(ChatUsage(user_id=user.id))
            session.commit()
            seed_knowledge_chain(session, tmp_path, user, vectors=1)
        with engine.begin() as connection:
            profile_id = uuid4()
            now = datetime(2026, 10, 22, 8, tzinfo=UTC)
            connection.execute(
                legacy.tables["model_profiles"]
                .insert()
                .values(
                    id=profile_id,
                    name="升级前默认模型",
                    kind="chat",
                    base_url="https://fixture.example/v1",
                    model="legacy-model",
                    api_key_encrypted="synthetic-existing-ciphertext",
                    enabled=True,
                    timeout_seconds=15,
                    max_retries=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                legacy.tables["model_bindings"].insert(),
                [
                    {
                        "kind": kind,
                        "profile_id": profile_id if kind == "chat" else None,
                        "revision": 7 if kind == "chat" else 0,
                    }
                    for kind in ("chat", "embedding", "rerank", "query_rewrite")
                ],
            )
            yield connection, legacy
    finally:
        engine.dispose()


# 验证迁移从当前 head 单向接续，不改写模型配置历史迁移或制造第二个 head。
def test_operations_migration_extends_existing_single_head():
    migration = operations_revision()
    assert migration.revision != migration.down_revision


# 验证迁移真正创建两张历史表和版本列，并逐行保留完整既有知识链路及配置。
def test_upgrade_adds_history_and_versions_without_changing_legacy_rows(
    tmp_path, fast_password_hasher
):
    migration = operations_revision()
    with seeded_legacy_database(tmp_path) as (connection, legacy):
        before = snapshot_legacy_rows(connection, legacy)
        assert before["document_embeddings"] and before["chat_usage"] and before["user_sessions"]
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        inspector = inspect(connection)
        assert set(inspector.get_table_names()) >= NEW_TABLES, "迁移未实际创建审计或诊断表。"
        version = next(
            (
                column
                for column in inspector.get_columns("model_profiles")
                if column["name"] == "revision"
            ),
            None,
        )
        assert version and not version["nullable"], (
            "已有配置必须补齐非空 revision，不能让历史配置失去版本。"
        )
        assert connection.execute(text("SELECT revision FROM model_profiles")).scalar_one() == 1
        assert snapshot_legacy_rows(connection, legacy) == before, (
            "后台增量迁移改变了既有账号、凭据、会话、额度、资料、向量或默认绑定；应逐行保持。"
        )
        assert (
            str(legacy.tables["document_embeddings"].c.embedding_vector.type).upper()
            == "VECTOR(2560)"
        )


# 验证隔离库升级/降级/再升级可执行，且降级只移除本次结构、不丢失业务行。
def test_isolated_roundtrip_preserves_all_legacy_rows(tmp_path, fast_password_hasher):
    migration = operations_revision()
    with seeded_legacy_database(tmp_path) as (connection, legacy):
        before = snapshot_legacy_rows(connection, legacy)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.downgrade()
            assert not NEW_TABLES & set(inspect(connection).get_table_names())
            assert "revision" not in {
                column["name"] for column in inspect(connection).get_columns("model_profiles")
            }
            assert snapshot_legacy_rows(connection, legacy) == before, (
                "隔离库降级破坏了既有业务数据。"
            )
            migration.upgrade()
        assert set(inspect(connection).get_table_names()) >= NEW_TABLES
        assert snapshot_legacy_rows(connection, legacy) == before, (
            "再次升级不能改写旧资料归属或向量。"
        )
