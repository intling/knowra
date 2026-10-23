"""额度模型约束与 Alembic 迁移的 RED 测试。"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa

VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def migration_module():
    paths = list(VERSIONS.glob("*_add_chat_quota.py"))
    assert len(paths) == 1, "需要独立的 add_chat_quota 增量迁移，不能改写用户体系历史迁移"
    spec = importlib.util.spec_from_file_location("chat_quota_migration", paths[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# 验证额度迁移历史父节点及后继模型迁移不变，允许唯一 head 继续增量演进。
def test_quota_migration_follows_auth_and_is_single_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    migration = migration_module()
    assert migration.down_revision == "20261021_0001"
    config = Config()
    config.set_main_option("script_location", str(VERSIONS.parent))
    scripts = ScriptDirectory.from_config(config)
    assert len(scripts.get_heads()) == 1, "额度迁移之后必须保持唯一迁移头，不能新增分支。"
    assert migration.revision in {revision.revision for revision in scripts.walk_revisions()}, (
        "额度迁移必须保留在当前 head 的祖先链中，不能改写或移除历史。"
    )
    assert scripts.get_revision("20261022_0001").down_revision == migration.revision


# 验证新增两表的主键、外键、正整数额度约束、时区时间与用户/时间复合索引。
def test_quota_upgrade_creates_constrained_tables_and_index(monkeypatch):
    migration = migration_module()
    tables, indexes, executed = {}, [], []
    monkeypatch.setattr(
        migration.op, "create_table", lambda name, *cols, **kw: tables.update({name: cols})
    )
    monkeypatch.setattr(migration.op, "create_index", lambda *args, **kw: indexes.append(args))
    monkeypatch.setattr(migration.op, "execute", executed.append)

    migration.upgrade()

    assert set(tables) == {"user_chat_limits", "chat_usage"}
    limits = {col.name: col for col in tables["user_chat_limits"] if isinstance(col, sa.Column)}
    assert limits["user_id"].primary_key
    assert any(fk.target_fullname == "users.id" for fk in limits["user_id"].foreign_keys)
    assert not limits["hourly_limit"].nullable
    checks = [col for col in tables["user_chat_limits"] if isinstance(col, sa.CheckConstraint)]
    assert any("hourly_limit > 0" in str(check.sqltext) for check in checks)
    usages = {col.name: col for col in tables["chat_usage"] if isinstance(col, sa.Column)}
    assert usages["id"].primary_key
    assert any(fk.target_fullname == "users.id" for fk in usages["user_id"].foreign_keys)
    assert not usages["created_at"].nullable and usages["created_at"].type.timezone
    assert any(
        table == "chat_usage" and tuple(cols) == ("user_id", "created_at")
        for _, table, cols in indexes
    )
    assert executed == [], "迁移不应修改已有账号、资料、密码或使用记录"


# 验证降级只移除本次额度结构，不删除用户体系、资料或认证表。
def test_quota_downgrade_only_removes_quota_tables(monkeypatch):
    migration = migration_module()
    dropped = []
    monkeypatch.setattr(migration.op, "drop_index", lambda *args, **kw: None)
    monkeypatch.setattr(migration.op, "drop_table", dropped.append)

    migration.downgrade()

    assert dropped == ["chat_usage", "user_chat_limits"]
