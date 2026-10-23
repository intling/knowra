"""可选真实 PostgreSQL 验证，每个测试只写入独立临时 schema。"""

import json
import os
from base64 import urlsafe_b64encode
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import Settings
from app.core.errors import AppError
from app.models.admin_operations import AdminAuditEvent
from app.models.document_embedding import DocumentEmbeddingJob
from app.models.model_configuration import MODEL_KINDS, ModelBinding, ModelProfile
from app.models.user import User, UserCredential, UserSession
from app.schemas.auth import AdminUserCreate, AdminUserUpdate
from app.schemas.model_configuration import ModelCreate, ModelUpdate
from app.services import model_configuration, user_admin
from app.services.model_configuration import change_binding, lock_model_binding
from app.services.user_admin import delete_user, lock_admins, update_user
from tests.admin_console.helpers import MODEL_KEY, profile_payload
from tests.admin_console.test_audit_transactions import (
    EXISTING_ACTIONS,
    NEW_PASSWORD,
    REPLACEMENT_KEY,
    business_snapshot,
)
from tests.auth_helpers import issue_session_token, make_account, seed_knowledge_chain


@pytest.fixture
def postgres_engine(fast_password_hasher):
    url = os.environ.get("ADMIN_TEST_DATABASE_URL")
    if not url:
        pytest.skip("设置 ADMIN_TEST_DATABASE_URL 以运行独立 PostgreSQL 并发验证")
    schema = "admin_test_" + uuid4().hex
    control = create_engine(url)
    with control.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url,
        connect_args={
            "options": (
                f"-csearch_path={schema},public -clock_timeout=5000 -cstatement_timeout=10000"
            )
        },
    ).execution_options(schema_translate_map={None: schema})
    try:
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            session.add_all([ModelBinding(kind=kind) for kind in MODEL_KINDS])
            session.commit()
        yield engine
    finally:
        engine.dispose()
        with control.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        control.dispose()


def _result(operation):
    try:
        operation()
        return "ok"
    except AppError as error:
        return error.code


# 验证两位管理员同时降级自己，只能成功一位，始终保留一个有效管理员。
def test_concurrent_self_demotion_keeps_last_admin(postgres_engine):
    with Session(postgres_engine) as session:
        ids = [make_account(session, role="admin").id for _ in range(2)]
    barrier = Barrier(2)

    def demote(user_id):
        with Session(postgres_engine) as session:
            actor = session.get(User, user_id)
            barrier.wait(timeout=5)
            return _result(
                lambda: update_user(session, actor, user_id, AdminUserUpdate(role="member"))
            )

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(demote, ids)) == ["last_admin", "ok"]
    with Session(postgres_engine) as session:
        assert (
            len(
                session.exec(
                    select(User).where(
                        User.role == "admin", User.status == "active", User.deleted_at.is_(None)
                    )
                ).all()
            )
            == 1
        )
        rows = session.exec(select(AdminAuditEvent)).all()
        assert sorted(row.result for row in rows) == ["denied", "success"], (
            "并发降级应提交一次成功及一次拒绝审计，不能因回滚丢失拒绝记录。"
        )
        assert all(row.action == "user.update" for row in rows)
        assert next(row for row in rows if row.result == "denied").error_code == "last_admin"


# 验证相互删除时，失去管理员身份的在途请求被重新校验，删除与撤销会话同时落库。
def test_cross_delete_revalidates_actor_and_revokes_sessions(postgres_engine):
    with Session(postgres_engine) as session:
        users = [make_account(session, role="admin") for _ in range(2)]
        ids = [user.id for user in users]
        for user in users:
            issue_session_token(session, user)
    barrier = Barrier(2)

    def remove(index):
        with Session(postgres_engine) as session:
            actor = session.get(User, ids[index])
            barrier.wait(timeout=5)
            return _result(lambda: delete_user(session, actor, ids[1 - index]))

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(remove, range(2))) == ["forbidden", "ok"]
    with Session(postgres_engine) as session:
        removed = session.exec(select(User).where(User.deleted_at.is_not(None))).one()
        tokens = session.exec(select(UserSession).where(UserSession.user_id == removed.id)).all()
        assert tokens and all(token.revoked_at is not None for token in tokens)
        assert session.exec(
            select(User).where(User.deleted_at.is_(None), User.role == "admin")
        ).one()
        rows = session.exec(select(AdminAuditEvent)).all()
        assert sorted(row.result for row in rows) == ["denied", "success"], (
            "交叉删除只能提交一条成功审计，失权请求应独立记录 denied。"
        )
        assert next(row for row in rows if row.result == "denied").error_code == "forbidden"


# 验证同用途并发激活落在唯一绑定行，版本递增两次且不会出现多个默认。
def test_concurrent_activation_keeps_one_binding(postgres_engine):
    with Session(postgres_engine) as session:
        actor_id = make_account(session, role="admin").id
        profiles = [
            ModelProfile(
                name=f"chat-{index}",
                kind="chat",
                base_url="https://models.example/v1",
                model=f"chat-{index}",
            )
            for index in range(2)
        ]
        session.add_all(profiles)
        session.commit()
        ids = [profile.id for profile in profiles]
    barrier = Barrier(2)

    def activate(profile_id):
        with Session(postgres_engine) as session:
            actor = session.get(User, actor_id)
            barrier.wait(timeout=5)
            return change_binding(
                session, actor, profile_id, Settings(_env_file=None), activate=True
            )

    with ThreadPoolExecutor(2) as pool:
        list(pool.map(activate, ids))
    with Session(postgres_engine) as session:
        binding = session.get(ModelBinding, "chat")
        assert binding.profile_id in ids and binding.revision == 2
        assert (
            len(
                session.exec(select(ModelBinding).where(ModelBinding.profile_id.is_not(None))).all()
            )
            == 1
        )
        rows = session.exec(select(AdminAuditEvent)).all()
        assert len(rows) == 2 and all(row.result == "success" for row in rows)
        assert sorted(row.changes_json["binding_revision"]["after"] for row in rows) == [1, 2], (
            "默认绑定版本与成功审计必须在同一事务递增，不能覆盖或重复计数。"
        )


# 验证向量入队持锁期间的默认切换等待，随后看见 queued 作业并明确拒绝。
def test_embedding_admission_serializes_with_switch(postgres_engine, tmp_path):
    with Session(postgres_engine) as session:
        actor = make_account(session, role="admin")
        actor_id = actor.id
        seed_knowledge_chain(session, tmp_path / "uploads", actor, vectors=1)
        job = session.exec(select(DocumentEmbeddingJob)).one()
        chunk_job_id, parsed_id = job.chunk_job_id, job.parsed_document_id
        job.status = "failed"
        session.add(job)
        profile = ModelProfile(
            name="new-space",
            kind="embedding",
            base_url="https://new.example/v1",
            model="new",
            dimensions=2560,
        )
        session.add(profile)
        session.commit()
        profile_id = profile.id
    locked, attempted, release = Event(), Event(), Event()

    def admit():
        with Session(postgres_engine) as session:
            lock_model_binding(session, "embedding")
            locked.set()
            assert release.wait(timeout=5)
            job = DocumentEmbeddingJob(
                chunk_job_id=chunk_job_id,
                parsed_document_id=parsed_id,
                owner_user_id=actor_id,
                status="queued",
                model="old-space",
                dimensions=2560,
            )
            session.add(job)
            session.commit()

    def activate():
        with Session(postgres_engine) as session:
            actor = session.get(User, actor_id)
            # 显式等到用户锁已取得，再允许作业 INSERT，覆盖外键锁和绑定锁的交叉窗口。
            lock_admins(session, actor)
            attempted.set()
            return _result(
                lambda: change_binding(
                    session, actor, profile_id, Settings(_env_file=None), activate=True
                )
            )

    with ThreadPoolExecutor(2) as pool:
        admission = pool.submit(admit)
        assert locked.wait(timeout=5)
        switching = pool.submit(activate)
        assert attempted.wait(timeout=5)
        release.set()
        admission.result(timeout=10)
        assert switching.result(timeout=10) == "embedding_index_conflict"
    with Session(postgres_engine) as session:
        assert session.get(ModelBinding, "embedding").profile_id is None
        row = session.exec(select(AdminAuditEvent)).one()
        assert row.result == "denied" and row.error_code == "embedding_index_conflict"


# 验证两位管理员相互禁用时重新校验操作者，只成功一次并与会话撤销、审计共同提交。
def test_cross_disable_preserves_admin_and_audit_consistency(postgres_engine):
    with Session(postgres_engine) as session:
        users = [make_account(session, role="admin") for _ in range(2)]
        ids = [user.id for user in users]
        for user in users:
            issue_session_token(session, user)
    barrier = Barrier(2)

    def disable(index):
        with Session(postgres_engine) as session:
            actor = session.get(User, ids[index])
            barrier.wait(timeout=5)
            return _result(
                lambda: update_user(
                    session, actor, ids[1 - index], AdminUserUpdate(status="disabled")
                )
            )

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(disable, range(2))) == ["forbidden", "ok"]
    with Session(postgres_engine) as session:
        users = session.exec(select(User)).all()
        assert sum(user.status == "active" and user.role == "admin" for user in users) == 1
        disabled = next(user for user in users if user.status == "disabled")
        tokens = session.exec(select(UserSession).where(UserSession.user_id == disabled.id)).all()
        assert tokens and all(token.revoked_at is not None for token in tokens)
        rows = session.exec(select(AdminAuditEvent)).all()
        assert sorted(row.result for row in rows) == ["denied", "success"]
        assert next(row for row in rows if row.result == "success").resource_id == disabled.id


def invoke_admin_write(session, actor, target, profile, action, settings):
    operations = {
        "user.create": lambda: user_admin.create_user(
            session,
            actor,
            AdminUserCreate(
                email="postgres-created@example.com", display_name="合成用户", password=NEW_PASSWORD
            ),
        ),
        "user.update": lambda: user_admin.update_user(
            session, actor, target.id, AdminUserUpdate(role="viewer", status="disabled")
        ),
        "user.reset_password": lambda: user_admin.reset_password(
            session, actor, target.id, NEW_PASSWORD
        ),
        "user.delete": lambda: user_admin.delete_user(session, actor, target.id),
        "model.create": lambda: model_configuration.create_profile(
            session, actor, ModelCreate.model_validate(profile_payload()), settings
        ),
        "model.update": lambda: model_configuration.update_profile(
            session,
            actor,
            profile.id,
            ModelUpdate(model="changed-model", api_key=REPLACEMENT_KEY),
            settings,
        ),
        "model.activate": lambda: model_configuration.change_binding(
            session, actor, profile.id, settings, activate=True
        ),
        "model.deactivate": lambda: model_configuration.change_binding(
            session, actor, profile.id, settings, activate=False
        ),
        "model.delete": lambda: model_configuration.delete_profile(session, actor, profile.id),
    }
    return operations[action]()


# 验证真实 PostgreSQL 拒绝成功审计 INSERT 后九类业务均完整回滚，并能单独提交失败事件。
@pytest.mark.parametrize("action", EXISTING_ACTIONS)
def test_postgres_audit_failure_rolls_back_all_business_rows(postgres_engine, action):
    settings = Settings(
        _env_file=None, model_config_encryption_key=urlsafe_b64encode(b"p" * 32).decode()
    )
    with Session(postgres_engine) as session:
        actor = make_account(session, role="admin")
        target = make_account(session)
        issue_session_token(session, target)
        profile = ModelProfile(
            name="合成配置", kind="chat", model="old-model", base_url="https://fixture.example/v1"
        )
        session.add(profile)
        session.commit()
        if action == "model.deactivate":
            binding = session.get(ModelBinding, "chat")
            binding.profile_id = profile.id
            session.add(binding)
            session.commit()
        before = business_snapshot(session)
        session.commit()
        session.execute(
            text("""
            CREATE FUNCTION reject_success_audit() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.result = 'success' THEN
                    RAISE EXCEPTION 'synthetic audit write failure';
                END IF;
                RETURN NEW;
            END $$
        """)
        )
        session.execute(
            text("""
            CREATE TRIGGER reject_success_audit BEFORE INSERT ON admin_audit_events
            FOR EACH ROW EXECUTE FUNCTION reject_success_audit()
        """)
        )
        session.commit()
        with pytest.raises(AppError) as caught:
            invoke_admin_write(session, actor, target, profile, action, settings)
        assert caught.value.status_code == 503 and caught.value.code == "admin_audit_unavailable", (
            f"{action} 审计失败应有明确的 503 原因，不能提交业务后返回成功。"
        )
        session.rollback()
        assert business_snapshot(session) == before, f"{action} 在审计失败后留下部分业务写入。"
        rows = session.exec(select(AdminAuditEvent)).all()
        assert len(rows) == 1 and rows[0].result == "failed", (
            "成功事务回滚后应单独记录 failed，不能残留 success 或丢失可写的失败记录。"
        )
        assert rows[0].action == action and rows[0].error_code == "admin_audit_unavailable"


# 验证 PostgreSQL JSON 审计与日志均不保存密码/哈希、会话材料、密钥明密文及完整服务地址。
def test_postgres_audit_and_logs_exclude_credentials(postgres_engine, caplog):
    settings = Settings(
        _env_file=None, model_config_encryption_key=urlsafe_b64encode(b"p" * 32).decode()
    )
    with Session(postgres_engine) as session:
        actor = make_account(session, role="admin")
        target = make_account(session)
        token = issue_session_token(session, target)
        original_hash = session.get(UserCredential, target.id).password_hash
        token_hash = (
            session.exec(select(UserSession).where(UserSession.user_id == target.id))
            .one()
            .token_hash
        )
        user_admin.reset_password(session, actor, target.id, NEW_PASSWORD)
        changed_hash = session.get(UserCredential, target.id).password_hash
        payload = profile_payload(
            name="private-profile-name-canary",
            base_url="https://private.example/v1/private-endpoint-canary",
        )
        profile = model_configuration.create_profile(
            session, actor, ModelCreate.model_validate(payload), settings
        )
        ciphertext = session.get(ModelProfile, profile.id).api_key_encrypted
        rows = session.exec(select(AdminAuditEvent)).all()
        assert len(rows) == 2 and all(row.result == "success" for row in rows)
        stored = json.dumps([row.model_dump(mode="json") for row in rows], ensure_ascii=False)
        for value in [
            NEW_PASSWORD,
            token,
            token_hash,
            original_hash,
            changed_hash,
            MODEL_KEY,
            ciphertext,
            settings.model_config_encryption_key,
            payload["name"],
            payload["base_url"],
        ]:
            assert value not in stored and value not in caplog.text, (
                "管理操作的 JSON 台账或结构化日志包含了凭据、显示名或完整地址。"
            )


# 验证原本不存在额度行时，准入仍等待账号额度锁，读取管理员提交后的新规则。
@pytest.mark.parametrize("initial,updated", [(None, 1), (2, None), (2, 1)])
def test_quota_change_serializes_admission_even_without_row(postgres_engine, initial, updated):
    from app.models.chat_quota import ChatUsage, UserChatLimit
    from app.services import chat_quota

    with Session(postgres_engine) as session:
        actor_id = make_account(session, role="admin").id
        target_id = make_account(session).id
        if initial:
            session.add(UserChatLimit(user_id=target_id, hourly_limit=initial))
        session.add(ChatUsage(user_id=target_id))
        session.commit()
    attempted = Event()

    def admit():
        with Session(postgres_engine) as session:
            attempted.set()
            try:
                reservation = chat_quota.reserve_chat(session, target_id)
                assert not session.in_transaction(), "准入事务锁不得跨网络调用"
                return "unlimited" if reservation is None else "limited"
            except AppError as error:
                return error.code

    with Session(postgres_engine) as writer, ThreadPoolExecutor(1) as pool:
        chat_quota.lock_account_quota(writer, target_id)
        future = pool.submit(admit)
        assert attempted.wait(3)
        assert not future.done(), "无额度行也必须受相同事务锁保护"
        user_admin.set_chat_limit(writer, writer.get(User, actor_id), target_id, updated)
        assert future.result(timeout=5) == (
            "unlimited" if updated is None else "chat_quota_exceeded"
        )
    with Session(postgres_engine) as session:
        assert len(session.exec(select(ChatUsage).where(ChatUsage.user_id == target_id)).all()) == 1


# 验证无限额准入完成后立即释放事务锁，另一进程可以首次设限。
def test_unlimited_admission_releases_transaction_before_network(postgres_engine):
    from app.services import chat_quota

    with Session(postgres_engine) as session:
        target_id = make_account(session).id
        assert chat_quota.reserve_chat(session, target_id) is None
        assert not session.in_transaction(), "不限额路径也应完成短事务，不能持锁等待模型"


# 验证多连接 worker 同时准入，同配置冷却与全局名额均由数据库保护。
@pytest.mark.parametrize("same_profile", [True, False])
def test_probe_admission_is_shared_across_workers(postgres_engine, same_profile):
    from app.core.shutdown import ApplicationShutdownState
    from app.services.model_probes import admit_probe

    with Session(postgres_engine) as session:
        actor_id = make_account(session, role="admin").id
        profiles = [
            ModelProfile(
                name=f"probe {i}", kind="chat", base_url="http://127.0.0.1:9/v1", model="probe"
            )
            for i in range(6)
        ]
        session.add_all(profiles)
        session.commit()
        ids = [p.id for p in profiles]
    barrier = Barrier(6)

    def attempt(index):
        with Session(postgres_engine) as session:
            actor = session.get(User, actor_id)
            barrier.wait(timeout=5)
            return _result(
                lambda: admit_probe(
                    session,
                    actor,
                    ids[0 if same_profile else index],
                    1,
                    Settings(_env_file=None),
                    ApplicationShutdownState(),
                )
            )

    with ThreadPoolExecutor(6) as pool:
        result = list(pool.map(attempt, range(6)))
    assert result.count("ok") == (1 if same_profile else 2), "跨 worker 必须共用冷却及并发边界"
    assert result.count("model_test_rate_limited") == (5 if same_profile else 4)


# 验证模型中途删除后 PostgreSQL 外键置空，旧版本结果与审计保留原资源标识。
def test_probe_deleted_profile_retains_safe_history(postgres_engine):
    from app.core.shutdown import ApplicationShutdownState
    from app.models.admin_operations import ModelProbeResult
    from app.services.model_probes import admit_probe, finish_probe

    with Session(postgres_engine) as session:
        actor = make_account(session, role="admin")
        profile = ModelProfile(
            name="deleted probe", kind="chat", base_url="http://127.0.0.1/v1", model="probe"
        )
        session.add(profile)
        session.commit()
        profile_id, actor_id = profile.id, actor.id
        probe_id, _ = admit_probe(
            session, actor, profile_id, 1, Settings(_env_file=None), ApplicationShutdownState()
        )
    with Session(postgres_engine) as session:
        model_configuration.delete_profile(session, session.get(User, actor_id), profile_id)
    with Session(postgres_engine) as session:
        result = finish_probe(
            session,
            session.get(User, actor_id),
            profile_id,
            probe_id,
            "passed",
            "model_test_passed",
            1,
        )
        assert not result.is_current
        assert session.get(ModelProbeResult, probe_id).profile_id is None
        assert (
            session.exec(select(AdminAuditEvent).where(AdminAuditEvent.action == "model.test"))
            .one()
            .resource_id
            == profile_id
        )
