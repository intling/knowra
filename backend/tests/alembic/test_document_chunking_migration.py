import importlib.util
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"

REQUIRED_COLUMNS = {
    "document_chunk_jobs": {
        "id",
        "parsed_document_id",
        "owner_user_id",
        "status",
        "chunker_name",
        "chunker_version",
        "chunk_config_json",
        "chunk_count",
        "attempt_count",
        "started_at",
        "finished_at",
        "error_code",
        "error_message",
        "created_at",
        "updated_at",
    },
    "document_chunks": {
        "id",
        "chunk_job_id",
        "parsed_document_id",
        "owner_user_id",
        "sequence_index",
        "text",
        "text_storage_key",
        "contextualized_text",
        "contextualized_text_storage_key",
        "token_count",
        "heading_path",
        "page_numbers",
        "chunk_type",
        "source_segment_indices",
        "metadata_json",
        "created_at",
    },
}

EXPECTED_INDEX_COLUMNS = {
    "document_chunk_jobs": {"owner_user_id", "parsed_document_id", "status"},
    "document_chunks": {"chunk_job_id", "parsed_document_id", "owner_user_id"},
}


class FakeInspector:
    def __init__(
        self,
        tables: set[str] | None = None,
        columns_by_table: dict[str, set[str]] | None = None,
    ) -> None:
        self.tables = tables or set()
        self.columns_by_table = columns_by_table or {}

    def has_table(self, table_name: str) -> bool:
        return table_name in self.tables

    def get_columns(self, table_name: str) -> list[dict[str, str]]:
        return [{"name": column_name} for column_name in self.columns_by_table[table_name]]


def patch_inspector(monkeypatch, migration: ModuleType, inspector: FakeInspector) -> None:
    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(migration.sa, "inspect", lambda bind: inspector)


def load_document_chunking_migration() -> ModuleType:
    candidates = sorted(MIGRATIONS_DIR.glob("*document_chunking*.py"))
    assert len(candidates) == 1, "Expected exactly one document_chunking Alembic migration"

    spec = importlib.util.spec_from_file_location("document_chunking_migration", candidates[0])
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


def test_document_chunking_migration_upgrade_creates_tables_foreign_keys_and_indexes(
    monkeypatch,
) -> None:
    migration = load_document_chunking_migration()
    created_tables: list[tuple[tuple[object, ...], dict[str, object]]] = []
    created_indexes: list[tuple[str, str, tuple[str, ...], dict[str, object]]] = []
    patch_inspector(monkeypatch, migration, FakeInspector())

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

    assert "parsed_documents.id" in collect_foreign_targets(tables["document_chunk_jobs"])
    assert "users.id" in collect_foreign_targets(tables["document_chunk_jobs"])
    assert "document_chunk_jobs.id" in collect_foreign_targets(tables["document_chunks"])
    assert "parsed_documents.id" in collect_foreign_targets(tables["document_chunks"])
    assert "users.id" in collect_foreign_targets(tables["document_chunks"])

    indexed_columns_by_table: dict[str, set[str]] = {}
    for _, table_name, column_names, _ in created_indexes:
        indexed_columns_by_table.setdefault(table_name, set()).update(column_names)

    for table_name, expected_columns in EXPECTED_INDEX_COLUMNS.items():
        assert expected_columns <= indexed_columns_by_table[table_name]
    assert any(
        table_name == "document_chunks" and column_names == ("parsed_document_id", "sequence_index")
        for _, table_name, column_names, _ in created_indexes
    )
    assert all(kwargs.get("if_not_exists") is True for _, kwargs in created_tables)
    assert all(kwargs.get("if_not_exists") is True for _, _, _, kwargs in created_indexes)


def test_document_chunking_migration_archives_legacy_document_chunks_before_create(
    monkeypatch,
) -> None:
    migration = load_document_chunking_migration()
    events: list[tuple[str, str, str | None]] = []
    patch_inspector(
        monkeypatch,
        migration,
        FakeInspector(
            tables={"document_chunks"},
            columns_by_table={"document_chunks": {"id", "document_id", "chunk_index"}},
        ),
    )
    monkeypatch.setattr(
        migration.op,
        "rename_table",
        lambda old_name, new_name: events.append(("rename", old_name, new_name)),
    )
    monkeypatch.setattr(
        migration.op,
        "drop_index",
        lambda name, table_name=None, **kwargs: events.append(("drop_index", name, table_name)),
    )
    monkeypatch.setattr(
        migration.op,
        "create_table",
        lambda table_name, *args, **kwargs: events.append(("create_table", table_name, None)),
    )
    monkeypatch.setattr(migration.op, "create_index", lambda *args, **kwargs: None)

    migration.upgrade()

    assert ("drop_index", "ix_document_chunks_owner_user_id", "document_chunks") in events
    rename_event = (
        "rename",
        "document_chunks",
        "legacy_document_chunks_20260612_0001",
    )
    create_event = ("create_table", "document_chunks", None)
    assert events.index(rename_event) < events.index(create_event)


def test_document_chunking_migration_keeps_current_document_chunks_table(
    monkeypatch,
) -> None:
    migration = load_document_chunking_migration()
    renamed_tables: list[tuple[str, str]] = []
    patch_inspector(
        monkeypatch,
        migration,
        FakeInspector(
            tables={"document_chunks"},
            columns_by_table={
                "document_chunks": {"id", "chunk_job_id", "parsed_document_id", "sequence_index"}
            },
        ),
    )
    monkeypatch.setattr(
        migration.op,
        "rename_table",
        lambda old_name, new_name: renamed_tables.append((old_name, new_name)),
    )
    monkeypatch.setattr(migration.op, "drop_index", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "create_table", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "create_index", lambda *args, **kwargs: None)

    migration.upgrade()

    assert renamed_tables == []


def test_document_chunking_migration_downgrade_drops_indexes_and_tables(monkeypatch) -> None:
    migration = load_document_chunking_migration()
    dropped_indexes: list[tuple[str, str | None, dict[str, object]]] = []
    dropped_tables: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(
        migration.op,
        "drop_index",
        lambda name, table_name=None, **kwargs: dropped_indexes.append((name, table_name, kwargs)),
    )
    monkeypatch.setattr(
        migration.op,
        "drop_table",
        lambda table_name, **kwargs: dropped_tables.append((table_name, kwargs)),
    )

    migration.downgrade()

    assert [table_name for table_name, _ in dropped_tables[:2]] == [
        "document_chunks",
        "document_chunk_jobs",
    ]
    assert {table_name for _, table_name, _ in dropped_indexes} >= set(REQUIRED_COLUMNS)
    assert all(kwargs.get("if_exists") is True for _, kwargs in dropped_tables)
    assert all(kwargs.get("if_exists") is True for _, _, kwargs in dropped_indexes)
