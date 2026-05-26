import importlib.util
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
REQUIRED_COLUMNS = {
    "id",
    "owner_user_id",
    "original_filename",
    "content_type",
    "byte_size",
    "storage_key",
    "checksum_sha256",
    "status",
    "error_message",
    "deleted_at",
    "created_at",
    "updated_at",
}


def load_uploaded_files_migration() -> ModuleType:
    candidates = sorted(MIGRATIONS_DIR.glob("*uploaded_files*.py"))
    assert len(candidates) == 1, "Expected exactly one uploaded_files Alembic migration"

    spec = importlib.util.spec_from_file_location(
        "uploaded_files_migration",
        candidates[0],
    )
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collect_foreign_targets(elements: tuple[object, ...]) -> set[str]:
    targets: set[str] = set()
    for element in elements:
        if isinstance(element, sa.Column):
            targets.update(foreign_key.target_fullname for foreign_key in element.foreign_keys)
        if isinstance(element, sa.ForeignKeyConstraint):
            targets.update(foreign_key.target_fullname for foreign_key in element.elements)
    return targets


def has_storage_key_unique_constraint(
    columns: dict[str, sa.Column],
    elements: tuple[object, ...],
    unique_constraints: list[tuple[str, str, tuple[str, ...]]],
) -> bool:
    if columns["storage_key"].unique:
        return True

    table_constraint = any(
        isinstance(element, sa.UniqueConstraint)
        and {column.name for column in element.columns} == {"storage_key"}
        for element in elements
    )
    if table_constraint:
        return True

    return any(
        table_name == "uploaded_files" and set(column_names) == {"storage_key"}
        for _, table_name, column_names in unique_constraints
    )


# 测试 Alembic upgrade 会创建 uploaded_files 表，
# 并包含模型承诺的字段、users.id 归属外键、storage_key 唯一约束和索引。
def test_uploaded_files_migration_upgrade_creates_table_constraints_and_indexes(
    monkeypatch,
) -> None:
    migration = load_uploaded_files_migration()
    created_tables: list[tuple[tuple[object, ...], dict[str, object]]] = []
    created_indexes: list[tuple[str, str, tuple[str, ...], dict[str, object]]] = []
    unique_constraints: list[tuple[str, str, tuple[str, ...]]] = []

    monkeypatch.setattr(
        migration.op,
        "create_table",
        lambda *args, **kwargs: created_tables.append((args, kwargs)),
    )
    monkeypatch.setattr(
        migration.op,
        "create_index",
        lambda name, table_name, columns, **kwargs: created_indexes.append(
            (name, table_name, tuple(columns), kwargs)
        ),
    )
    monkeypatch.setattr(
        migration.op,
        "create_unique_constraint",
        lambda name, table_name, columns, **kwargs: unique_constraints.append(
            (name, table_name, tuple(columns))
        ),
    )

    migration.upgrade()

    uploaded_files_tables = [
        (args, kwargs) for args, kwargs in created_tables if args[0] == "uploaded_files"
    ]
    assert len(uploaded_files_tables) == 1

    table_args, _ = uploaded_files_tables[0]
    elements = table_args[1:]
    columns = {element.name: element for element in elements if isinstance(element, sa.Column)}

    assert set(columns) == REQUIRED_COLUMNS
    assert columns["id"].primary_key
    assert not columns["owner_user_id"].nullable
    assert "users.id" in collect_foreign_targets(elements)
    assert has_storage_key_unique_constraint(columns, elements, unique_constraints)

    indexed_columns = {
        column_name
        for _, table_name, column_names, _ in created_indexes
        if table_name == "uploaded_files"
        for column_name in column_names
    }
    assert {"owner_user_id", "status", "created_at"} <= indexed_columns


# 测试 Alembic downgrade 会删除 uploaded_files 表及显式索引，
# 让回滚行为在生产代码实现前也可验证。
def test_uploaded_files_migration_downgrade_drops_table_and_indexes(monkeypatch) -> None:
    migration = load_uploaded_files_migration()
    dropped_indexes: list[tuple[str, str | None]] = []
    dropped_tables: list[str] = []

    monkeypatch.setattr(
        migration.op,
        "drop_index",
        lambda name, table_name=None, **kwargs: dropped_indexes.append((name, table_name)),
    )
    monkeypatch.setattr(migration.op, "drop_table", dropped_tables.append)

    migration.downgrade()

    assert "uploaded_files" in dropped_tables
    assert any(table_name == "uploaded_files" for _, table_name in dropped_indexes)
