import importlib.util
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"

# 本文件验证文档处理迁移会创建和回滚预期的表结构、约束与索引。

DOCUMENT_COLUMNS = {
    "id",
    "owner_user_id",
    "uploaded_file_id",
    "title",
    "source_content_type",
    "parser_name",
    "parser_version",
    "chunker_name",
    "chunker_version",
    "tokenizer_name",
    "tokenizer_version",
    "status",
    "chunk_count",
    "total_chars",
    "content_sha256",
    "metadata_json",
    "error_message",
    "deleted_at",
    "created_at",
    "updated_at",
}
CHUNK_COLUMNS = {
    "id",
    "document_id",
    "owner_user_id",
    "chunk_index",
    "content",
    "content_sha256",
    "char_start",
    "char_end",
    "token_count",
    "source_locator_json",
    "metadata_json",
    "created_at",
    "updated_at",
}


def load_document_processing_migration() -> ModuleType:
    candidates = sorted(MIGRATIONS_DIR.glob("*documents*.py"))
    assert len(candidates) == 1, "Expected exactly one documents Alembic migration"

    spec = importlib.util.spec_from_file_location(
        "document_processing_migration",
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


def has_unique_constraint(
    *,
    columns: dict[str, sa.Column],
    elements: tuple[object, ...],
    table_name: str,
    column_names: set[str],
    unique_constraints: list[tuple[str, str, tuple[str, ...]]],
) -> bool:
    if len(column_names) == 1 and columns[next(iter(column_names))].unique:
        return True

    table_constraint = any(
        isinstance(element, sa.UniqueConstraint)
        and {column.name for column in element.columns} == column_names
        for element in elements
    )
    if table_constraint:
        return True

    return any(
        constraint_table == table_name and set(constraint_columns) == column_names
        for _, constraint_table, constraint_columns in unique_constraints
    )


def collect_indexed_columns(
    created_indexes: list[tuple[str, str, tuple[str, ...], dict[str, object]]],
    table_name: str,
) -> set[tuple[str, ...]]:
    return {
        column_names
        for _, index_table, column_names, _ in created_indexes
        if index_table == table_name
    }


# 测试 upgrade 会创建 documents/document_chunks 表、外键、唯一约束和常用查询索引。
def test_document_processing_migration_upgrade_creates_tables_constraints_and_indexes(
    monkeypatch,
) -> None:
    migration = load_document_processing_migration()
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

    tables = {args[0]: args[1:] for args, _ in created_tables}
    assert {"documents", "document_chunks"} <= set(tables)

    document_elements = tables["documents"]
    document_columns = {
        element.name for element in document_elements if isinstance(element, sa.Column)
    }
    document_columns_by_name = {
        element.name: element for element in document_elements if isinstance(element, sa.Column)
    }

    assert document_columns == DOCUMENT_COLUMNS
    assert document_columns_by_name["id"].primary_key
    assert not document_columns_by_name["owner_user_id"].nullable
    assert not document_columns_by_name["uploaded_file_id"].nullable
    assert {"users.id", "uploaded_files.id"} <= collect_foreign_targets(document_elements)
    assert has_unique_constraint(
        columns=document_columns_by_name,
        elements=document_elements,
        table_name="documents",
        column_names={"uploaded_file_id"},
        unique_constraints=unique_constraints,
    )

    chunk_elements = tables["document_chunks"]
    chunk_columns = {element.name for element in chunk_elements if isinstance(element, sa.Column)}
    chunk_columns_by_name = {
        element.name: element for element in chunk_elements if isinstance(element, sa.Column)
    }

    assert chunk_columns == CHUNK_COLUMNS
    assert chunk_columns_by_name["id"].primary_key
    assert not chunk_columns_by_name["document_id"].nullable
    assert not chunk_columns_by_name["owner_user_id"].nullable
    assert {"documents.id", "users.id"} <= collect_foreign_targets(chunk_elements)
    assert has_unique_constraint(
        columns=chunk_columns_by_name,
        elements=chunk_elements,
        table_name="document_chunks",
        column_names={"document_id", "chunk_index"},
        unique_constraints=unique_constraints,
    )

    document_indexed_columns = collect_indexed_columns(created_indexes, "documents")
    assert {("owner_user_id",), ("uploaded_file_id",), ("status",), ("created_at",)} <= (
        document_indexed_columns
    )

    chunk_indexed_columns = collect_indexed_columns(created_indexes, "document_chunks")
    assert {("document_id",), ("owner_user_id",), ("document_id", "chunk_index")} <= (
        chunk_indexed_columns
    )


# 测试 downgrade 会删除迁移创建的索引和表，并按依赖顺序先删分块表。
def test_document_processing_migration_downgrade_drops_tables_and_indexes(monkeypatch) -> None:
    migration = load_document_processing_migration()
    dropped_indexes: list[tuple[str, str | None]] = []
    dropped_tables: list[str] = []

    monkeypatch.setattr(
        migration.op,
        "drop_index",
        lambda name, table_name=None, **kwargs: dropped_indexes.append((name, table_name)),
    )
    monkeypatch.setattr(migration.op, "drop_table", dropped_tables.append)

    migration.downgrade()

    assert dropped_tables == ["document_chunks", "documents"]
    assert any(table_name == "documents" for _, table_name in dropped_indexes)
    assert any(table_name == "document_chunks" for _, table_name in dropped_indexes)
