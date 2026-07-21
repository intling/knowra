"""本文件验证 add-embedding-vector-column Alembic 迁移的结构和数据回填逻辑。

覆盖：
- upgrade() 添加 ``embedding_vector vector(2560)`` 列
- 分批回填 ``embedding_json::vector`` → ``embedding_vector``
- 回填前数据完整性预检
- 回填后验证完整度
- downgrade() 删除 ``embedding_vector`` 列
"""

import importlib.util
from pathlib import Path
from types import ModuleType

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def load_embedding_vector_migration() -> ModuleType:
    """加载添加 embedding_vector 列的 Alembic 迁移模块。"""
    candidates = sorted(MIGRATIONS_DIR.glob("*add_embedding_vector_column*.py"))
    assert len(candidates) == 1, (
        f"Expected exactly one add_embedding_vector_column Alembic migration, "
        f"found {len(candidates)}: {[c.name for c in candidates]}"
    )

    spec = importlib.util.spec_from_file_location("embedding_vector_migration", candidates[0])
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ═══════════════════════════════════════════════════════════════════════════
# 迁移结构测试（Task 1.4）
# ═══════════════════════════════════════════════════════════════════════════


# upgrade() 必须添加 embedding_vector vector(2560) 列，回填后添加 NOT NULL 约束。
def test_upgrade_adds_embedding_vector_column(monkeypatch) -> None:
    migration = load_embedding_vector_migration()
    added_columns: list[tuple[str, str, object]] = []
    altered_columns: list[tuple[str, str, object]] = []

    monkeypatch.setattr(
        migration.op,
        "add_column",
        lambda table_name, column, **kwargs: added_columns.append(
            (table_name, str(column.type), column)
        ),
    )
    monkeypatch.setattr(
        migration.op,
        "alter_column",
        lambda table_name, column_name, **kwargs: altered_columns.append(
            (table_name, column_name, kwargs)
        ),
    )
    # 阻止回填逻辑实际执行
    monkeypatch.setattr(migration.op, "execute", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "get_bind", lambda: object())

    migration.upgrade()

    # 验证添加了 embedding_vector 列（初始 nullable）
    embedding_vector_adds = [
        (table, col_type, col)
        for table, col_type, col in added_columns
        if col.name == "embedding_vector"
    ]
    assert len(embedding_vector_adds) >= 1, (
        f"Expected add_column for embedding_vector, got: "
        f"{[(t, c.name) for t, _, c in added_columns]}"
    )

    table_name, col_type_str, column = embedding_vector_adds[0]
    assert table_name == "document_embeddings"
    assert "VECTOR" in col_type_str.upper()
    assert "2560" in col_type_str.upper()
    assert column.nullable is True, (
        "embedding_vector must be added as nullable for progressive backfill"
    )

    # 回填后必须通过 alter_column 设置 NOT NULL 约束
    not_null_alters = [
        (table, col_name, kwargs)
        for table, col_name, kwargs in altered_columns
        if col_name == "embedding_vector" and kwargs.get("nullable") is False
    ]
    assert len(not_null_alters) >= 1, (
        f"Expected alter_column to set embedding_vector NOT NULL after backfill, "
        f"got: {altered_columns}"
    )


# downgrade() 必须删除 embedding_vector 列，保持 embedding_json 完整。
def test_downgrade_drops_embedding_vector_column(monkeypatch) -> None:
    migration = load_embedding_vector_migration()
    dropped_columns: list[tuple[str, str]] = []

    monkeypatch.setattr(
        migration.op,
        "drop_column",
        lambda table_name, column_name, **kwargs: dropped_columns.append((table_name, column_name)),
    )

    migration.downgrade()

    assert ("document_embeddings", "embedding_vector") in dropped_columns, (
        f"Expected drop_column for embedding_vector, got: {dropped_columns}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# 回填逻辑测试（Task 1.3）
# ═══════════════════════════════════════════════════════════════════════════


# 回填前必须执行数据完整性预检：检查 jsonb_array_length(embedding_json) != 2560 的行。
def test_backfill_pre_check_validates_dimensions(monkeypatch) -> None:
    migration = load_embedding_vector_migration()
    executed_statements: list[str] = []

    monkeypatch.setattr(migration.op, "add_column", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "alter_column", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda stmt, *args: executed_statements.append(str(stmt)),
    )

    migration.upgrade()

    # 应该有一条预检语句检查维度不匹配的行
    pre_check_stmts = [s for s in executed_statements if "jsonb_array_length" in s and "2560" in s]
    assert len(pre_check_stmts) >= 1, (
        f"Expected pre-check SQL with jsonb_array_length, got: {executed_statements}"
    )


# 回填必须使用 embedding_json::vector 类型转换，每批 LIMIT 500，WHERE embedding_vector IS NULL。
def test_backfill_uses_vector_cast_with_batching(monkeypatch) -> None:
    migration = load_embedding_vector_migration()
    executed_statements: list[str] = []

    monkeypatch.setattr(migration.op, "add_column", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "alter_column", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda stmt, *args: executed_statements.append(str(stmt)),
    )

    migration.upgrade()

    # 回填 SQL 必须包含 ::vector 类型转换
    backfill_stmts = [
        s
        for s in executed_statements
        if "::vector" in s and "embedding_vector" in s and "embedding_json" in s
    ]
    assert len(backfill_stmts) >= 1, (
        f"Expected backfill SQL with ::vector cast, got: {executed_statements}"
    )

    # 回填必须使用 WHERE embedding_vector IS NULL 保证幂等
    assert any("embedding_vector IS NULL" in s for s in backfill_stmts), (
        "Backfill must filter WHERE embedding_vector IS NULL for idempotency"
    )

    # 回填必须分批，每批不超过 500 行
    assert any("LIMIT" in s and "500" in s for s in backfill_stmts), (
        "Backfill must batch with LIMIT 500"
    )


# 回填后必须验证完整度：确认 embedding_vector IS NULL 的行数为 0。
def test_backfill_post_verification_checks_null_count(monkeypatch) -> None:
    migration = load_embedding_vector_migration()
    executed_statements: list[str] = []

    monkeypatch.setattr(migration.op, "add_column", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "alter_column", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda stmt, *args: executed_statements.append(str(stmt)),
    )

    migration.upgrade()

    # 应该有验证语句检查 embedding_vector IS NULL 的行数
    verify_stmts = [s for s in executed_statements if "embedding_vector IS NULL" in s]
    # 至少应该有一条回填后的验证语句
    assert len(verify_stmts) >= 1, (
        f"Expected post-backfill verification for embedding_vector IS NULL, "
        f"got: {executed_statements}"
    )


# 降级后再次升级必须幂等（WHERE embedding_vector IS NULL 确保已回填的行被跳过）。
def test_backfill_is_idempotent(monkeypatch) -> None:
    """验证回填的可重入性：WHERE embedding_vector IS NULL 保障幂等。

    此测试验证迁移结构支持幂等重跑 —— 如果 upgrade 被中断后重新执行，
    已回填的行被跳过，未回填的继续处理。
    """
    migration = load_embedding_vector_migration()
    executed_statements: list[str] = []

    monkeypatch.setattr(migration.op, "add_column", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "alter_column", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(
        migration.op,
        "execute",
        lambda stmt, *args: executed_statements.append(str(stmt)),
    )

    migration.upgrade()

    # 所有更新语句必须通过 WHERE embedding_vector IS NULL 保证幂等
    update_stmts = [s for s in executed_statements if "UPDATE" in s.upper()]
    for stmt in update_stmts:
        assert "embedding_vector IS NULL" in stmt, (
            f"UPDATE must filter WHERE embedding_vector IS NULL for idempotency: {stmt}"
        )
