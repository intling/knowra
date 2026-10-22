"""模型配置迁移必须独立增量、初始化四种用途且可无损降级。"""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


# 验证真实执行增量迁移能够创建两表和四种绑定，降级只删除本次表。
def test_model_migration_upgrade_and_downgrade():
    paths = list(
        (Path(__file__).parents[2] / "alembic" / "versions").glob("*_add_model_configuration.py")
    )
    assert len(paths) == 1, "缺少模型配置独立迁移，不能仅依赖 create_all 建表"
    spec = importlib.util.spec_from_file_location("model_configuration_migration", paths[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "20261021_0002"
    with create_engine("sqlite://").begin() as connection:
        connection.execute(text("CREATE TABLE retained_data (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO retained_data VALUES (1)"))
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            assert {"model_profiles", "model_bindings"} <= set(
                inspect(connection).get_table_names()
            )
            assert set(connection.execute(text("SELECT kind FROM model_bindings")).scalars()) == {
                "chat",
                "embedding",
                "rerank",
                "query_rewrite",
            }
            module.downgrade()
        assert inspect(connection).get_table_names() == ["retained_data"]
        assert connection.execute(text("SELECT COUNT(*) FROM retained_data")).scalar() == 1
