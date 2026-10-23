"""在本机一次性 knowra_verify 数据库验证真实 Alembic 升降级；禁止用于业务库。"""

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlmodel import Session

from app.core.logging import get_logger
from app.models.chat_quota import ChatUsage, UserChatLimit
from tests.admin_console.test_operations_migration import (
    BASELINE_REVISION,
    NEW_TABLES,
    legacy_metadata,
    snapshot_legacy_rows,
)
from tests.auth_helpers import issue_session_token, make_account, seed_knowledge_chain

logger = get_logger(__name__)
BACKEND = Path(__file__).resolve().parents[4] / "backend"


def main():
    url = os.environ["ADMIN_MIGRATION_TEST_DATABASE_URL"]
    parsed = make_url(url)
    if parsed.database != "knowra_verify" or parsed.host not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("本脚本只允许操作本机一次性 knowra_verify 数据库，拒绝业务库。")
    environment = dict(os.environ, DATABASE_URL=url)

    def alembic(*arguments):
        subprocess.run(
            [sys.executable, "-m", "alembic", *arguments],
            cwd=BACKEND,
            env=environment,
            check=True,
        )

    alembic("upgrade", BASELINE_REVISION)
    engine = create_engine(url)
    legacy = legacy_metadata()
    try:
        with TemporaryDirectory(prefix="knowra-admin-migration-") as directory:
            with Session(engine) as session:
                user = make_account(session, email="migration-admin@example.com", role="admin")
                issue_session_token(session, user)
                session.add(UserChatLimit(user_id=user.id, hourly_limit=3))
                session.add(ChatUsage(user_id=user.id))
                session.commit()
                seed_knowledge_chain(session, Path(directory), user, vectors=1)
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
                    legacy.tables["model_bindings"]
                    .update()
                    .where(legacy.tables["model_bindings"].c.kind == "chat")
                    .values(profile_id=profile_id, revision=7)
                )
                before = snapshot_legacy_rows(connection, legacy)
            assert before["document_embeddings"] and before["chat_usage"]
            assert before["user_credentials"] and before["user_sessions"]

            def verify(stage, upgraded):
                with engine.connect() as connection:
                    inspector = inspect(connection)
                    tables = set(inspector.get_table_names())
                    assert (tables >= NEW_TABLES) if upgraded else not (NEW_TABLES & tables)
                    columns = {c["name"]: c for c in inspector.get_columns("model_profiles")}
                    if upgraded:
                        assert not columns["revision"]["nullable"]
                        assert (
                            connection.execute(
                                text("SELECT revision FROM model_profiles")
                            ).scalar_one()
                            == 1
                        )
                        audit_indexes = {
                            i["name"] for i in inspector.get_indexes("admin_audit_events")
                        }
                        assert audit_indexes >= {
                            "ix_admin_audit_created_id",
                            "ix_admin_audit_actor_created",
                            "ix_admin_audit_action_created",
                            "ix_admin_audit_trace_id",
                        }
                        probe_indexes = {
                            i["name"] for i in inspector.get_indexes("model_probe_results")
                        }
                        assert probe_indexes >= {
                            "ix_model_probe_profile_started",
                            "ix_model_probe_lease_expires",
                        }
                        profile_fk = next(
                            fk
                            for fk in inspector.get_foreign_keys("model_probe_results")
                            if fk["constrained_columns"] == ["profile_id"]
                        )
                        assert profile_fk["options"]["ondelete"] == "SET NULL"
                    else:
                        assert "revision" not in columns
                    assert snapshot_legacy_rows(connection, legacy) == before, (
                        f"{stage} 改变了账号、会话、额度或完整知识链路中的旧行。"
                    )
                    assert (
                        connection.execute(
                            text("SELECT vector_dims(embedding_vector) FROM document_embeddings")
                        ).scalar_one()
                        == 2560
                    )
                    logger.info(
                        "隔离数据库迁移数据保留验证通过",
                        stage=stage,
                        revision=connection.execute(
                            text("SELECT version_num FROM alembic_version")
                        ).scalar_one(),
                        legacy_table_count=len(legacy.tables),
                        legacy_row_count=sum(map(len, before.values())),
                        vector_dimensions=2560,
                    )

            alembic("upgrade", "head")
            verify("upgrade", True)
            alembic("downgrade", BASELINE_REVISION)
            verify("downgrade", False)
            alembic("upgrade", "head")
            verify("re-upgrade", True)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
