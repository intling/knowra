# 用户体系红测试：Alembic 迁移、SQLModel 模型约束与认证配置启动校验。

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.core.config import Settings
from app.models.user import User, UserCredential, UserSession

VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def load_auth_migration() -> ModuleType:
    candidates = sorted(VERSIONS_DIR.glob("*_add_user_auth_rbac.py"))
    assert len(candidates) == 1, "应存在且仅存在一个 add_user_auth_rbac 迁移"
    spec = importlib.util.spec_from_file_location("add_user_auth_rbac_migration", candidates[0])
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def table_columns(args: tuple) -> dict[str, sa.Column]:
    return {element.name: element for element in args[1:] if isinstance(element, sa.Column)}


def foreign_targets(column: sa.Column) -> set[str]:
    return {fk.target_fullname for fk in column.foreign_keys}


# 验证认证迁移历史父节点不变，且仍处于唯一 head 的祖先链，允许后续增量迁移。
def test_auth_migration_is_new_single_head() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    migration = load_auth_migration()
    assert migration.down_revision == "20260812_0002"
    config = Config()
    config.set_main_option("script_location", str(VERSIONS_DIR.parent))
    scripts = ScriptDirectory.from_config(config)
    assert len(scripts.get_heads()) == 1, "认证迁移之后必须保持唯一迁移头，不能新增分支。"
    assert migration.revision in {revision.revision for revision in scripts.walk_revisions()}, (
        "认证迁移必须保留在当前 head 的祖先链中，不能改写或移除历史。"
    )


# 验证 upgrade：users 增加带默认值和 CHECK 的 role；新建凭据表与会话表；不改写资源或默认用户数据。
def test_auth_migration_upgrade_adds_role_and_auth_tables(monkeypatch) -> None:
    migration = load_auth_migration()
    added_columns: list[tuple[str, sa.Column]] = []
    checks: list[tuple[str, str, str]] = []
    tables: dict[str, tuple] = {}
    indexes: list[tuple[str, str, tuple[str, ...], dict]] = []
    executed: list[object] = []

    monkeypatch.setattr(
        migration.op,
        "add_column",
        lambda table, column, **kw: added_columns.append((table, column)),
    )
    monkeypatch.setattr(
        migration.op,
        "create_check_constraint",
        lambda name, table, condition, **kw: checks.append((name, table, str(condition))),
    )
    monkeypatch.setattr(
        migration.op,
        "create_table",
        lambda name, *cols, **kw: tables.__setitem__(name, (name, *cols)),
    )
    monkeypatch.setattr(
        migration.op,
        "create_index",
        lambda name, table, columns, **kw: indexes.append((name, table, tuple(columns), kw)),
    )
    monkeypatch.setattr(migration.op, "execute", executed.append)

    migration.upgrade()

    assert [(table, column.name) for table, column in added_columns] == [("users", "role")]
    role = added_columns[0][1]
    assert role.nullable is False
    assert "member" in str(role.server_default.arg)
    assert any(
        table == "users" and all(r in condition for r in ("admin", "member", "viewer"))
        for _, table, condition in checks
    )

    credentials = table_columns(tables["user_credentials"])
    assert set(credentials) == {"user_id", "password_hash", "created_at", "updated_at"}
    assert credentials["user_id"].primary_key
    assert "users.id" in foreign_targets(credentials["user_id"])
    assert not credentials["password_hash"].nullable

    sessions = table_columns(tables["user_sessions"])
    assert set(sessions) == {
        "id",
        "user_id",
        "token_hash",
        "created_at",
        "expires_at",
        "revoked_at",
    }
    assert "users.id" in foreign_targets(sessions["user_id"])
    assert sessions["token_hash"].unique
    assert sessions["revoked_at"].nullable
    assert not sessions["expires_at"].nullable
    assert any(table == "user_sessions" and "user_id" in cols for _, table, cols, _ in indexes)
    assert executed == [], "迁移不得改写默认用户或资源归属数据"


# 验证 downgrade 删除新表、约束与 role 列。
def test_auth_migration_downgrade_drops_auth_structures(monkeypatch) -> None:
    migration = load_auth_migration()
    dropped_tables: list[str] = []
    dropped_columns: list[tuple[str, str]] = []
    dropped_constraints: list[tuple[str, str]] = []

    monkeypatch.setattr(migration.op, "drop_table", lambda name, **kw: dropped_tables.append(name))
    monkeypatch.setattr(migration.op, "drop_index", lambda *args, **kw: None)
    monkeypatch.setattr(
        migration.op,
        "drop_column",
        lambda table, column, **kw: dropped_columns.append((table, column)),
    )
    monkeypatch.setattr(
        migration.op,
        "drop_constraint",
        lambda name, table, **kw: dropped_constraints.append((name, table)),
    )

    migration.downgrade()

    assert {"user_credentials", "user_sessions"} <= set(dropped_tables)
    assert ("users", "role") in dropped_columns
    assert any(table == "users" for _, table in dropped_constraints)


# 验证模型：role 默认 member，非法角色被数据库 CHECK 拒绝；凭据与会话表名正确。
def test_user_model_role_default_and_check(auth_db: Session) -> None:
    user = User(display_name="Alice")
    auth_db.add(user)
    auth_db.commit()
    auth_db.refresh(user)
    assert user.role == "member"
    assert UserCredential.__tablename__ == "user_credentials"
    assert UserSession.__tablename__ == "user_sessions"

    auth_db.add(User(display_name="Root", role="root"))
    with pytest.raises(IntegrityError):
        auth_db.commit()


# 验证认证相关配置默认值。
def test_auth_settings_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.auth_cookie_secure is False
    assert settings.auth_session_ttl_hours == 336
    assert settings.auth_login_max_failures == 5
    assert settings.auth_login_window_seconds == 900


# 验证不安全配置在启动时失败：CORS 通配符，或生产环境使用非 Secure Cookie。
@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"backend_cors_origins": "*"}, "BACKEND_CORS_ORIGINS"),
        ({"backend_cors_origins": "http://localhost:5173,*"}, "BACKEND_CORS_ORIGINS"),
        ({"app_env": "production", "auth_cookie_secure": False}, "AUTH_COOKIE_SECURE"),
    ],
)
def test_insecure_auth_settings_fail_fast(overrides: dict, fragment: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, **overrides)
    assert fragment in str(exc_info.value), "启动失败信息必须指出具体配置项"


# 验证生产环境启用 Secure Cookie 时配置合法。
def test_production_with_secure_cookie_is_valid() -> None:
    settings = Settings(_env_file=None, app_env="production", auth_cookie_secure=True)
    assert settings.auth_cookie_secure is True
