import importlib.util
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"

REQUIRED_COLUMNS = {
    "document_parse_jobs": {
        "id",
        "uploaded_file_id",
        "owner_user_id",
        "status",
        "parser_name",
        "parser_version",
        "attempt_count",
        "started_at",
        "finished_at",
        "error_code",
        "error_message",
        "created_at",
        "updated_at",
    },
    "parsed_documents": {
        "id",
        "uploaded_file_id",
        "parse_job_id",
        "owner_user_id",
        "source_checksum_sha256",
        "markdown_storage_key",
        "text_storage_key",
        "docling_json_storage_key",
        "title",
        "page_count",
        "metadata_json",
        "created_at",
    },
    "document_segments": {
        "id",
        "parsed_document_id",
        "owner_user_id",
        "sequence_index",
        "segment_type",
        "page_no",
        "heading_path",
        "text",
        "metadata_json",
        "created_at",
    },
}

EXPECTED_INDEX_COLUMNS = {
    "document_parse_jobs": {"owner_user_id", "uploaded_file_id", "status"},
    "parsed_documents": {"uploaded_file_id", "parse_job_id"},
    "document_segments": {"parsed_document_id", "owner_user_id", "sequence_index"},
}


def load_document_parsing_migration() -> ModuleType:
    candidates = sorted(MIGRATIONS_DIR.glob("*document_parsing*.py"))
    assert len(candidates) == 1, "Expected exactly one document_parsing Alembic migration"

    spec = importlib.util.spec_from_file_location("document_parsing_migration", candidates[0])
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


# 测试解析 migration 会创建三张表、关键外键和索引。
def test_document_parsing_migration_upgrade_creates_tables_foreign_keys_and_indexes(
    monkeypatch,
) -> None:
    migration = load_document_parsing_migration()
    created_tables: list[tuple[tuple[object, ...], dict[str, object]]] = []
    created_indexes: list[tuple[str, str, tuple[str, ...], dict[str, object]]] = []

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

    migration.upgrade()

    tables = {args[0]: args[1:] for args, _ in created_tables}
    assert set(REQUIRED_COLUMNS) <= set(tables)

    for table_name, required_columns in REQUIRED_COLUMNS.items():
        columns = {element.name for element in tables[table_name] if isinstance(element, sa.Column)}
        assert columns == required_columns

    assert "uploaded_files.id" in collect_foreign_targets(tables["document_parse_jobs"])
    assert "users.id" in collect_foreign_targets(tables["document_parse_jobs"])
    assert "document_parse_jobs.id" in collect_foreign_targets(tables["parsed_documents"])
    assert "parsed_documents.id" in collect_foreign_targets(tables["document_segments"])

    indexed_columns_by_table: dict[str, set[str]] = {}
    for _, table_name, column_names, _ in created_indexes:
        indexed_columns_by_table.setdefault(table_name, set()).update(column_names)

    for table_name, expected_columns in EXPECTED_INDEX_COLUMNS.items():
        assert expected_columns <= indexed_columns_by_table[table_name]


# 测试解析 migration downgrade 会撤销显式索引并按依赖顺序删除表。
def test_document_parsing_migration_downgrade_drops_indexes_and_tables(monkeypatch) -> None:
    migration = load_document_parsing_migration()
    dropped_indexes: list[tuple[str, str | None]] = []
    dropped_tables: list[str] = []

    monkeypatch.setattr(
        migration.op,
        "drop_index",
        lambda name, table_name=None, **kwargs: dropped_indexes.append((name, table_name)),
    )
    monkeypatch.setattr(migration.op, "drop_table", dropped_tables.append)

    migration.downgrade()

    assert dropped_tables[:3] == [
        "document_segments",
        "parsed_documents",
        "document_parse_jobs",
    ]
    assert {table_name for _, table_name in dropped_indexes} >= set(REQUIRED_COLUMNS)
