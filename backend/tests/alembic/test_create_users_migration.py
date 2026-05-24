import importlib.util
from pathlib import Path
from types import ModuleType
from uuid import UUID

import sqlalchemy as sa

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260523_0001_create_users.py"
)


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "migration_20260523_0001_create_users",
        MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_user_seed_binds_id_as_uuid(monkeypatch) -> None:
    migration = load_migration()
    executed_statements: list[sa.TextClause] = []

    monkeypatch.setattr(migration.op, "create_table", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "create_index", lambda *args, **kwargs: None)
    monkeypatch.setattr(migration.op, "execute", executed_statements.append)

    migration.upgrade()

    assert len(executed_statements) == 1
    id_param = executed_statements[0]._bindparams["id"]

    assert isinstance(id_param.value, UUID)
    assert isinstance(id_param.type, sa.Uuid)
