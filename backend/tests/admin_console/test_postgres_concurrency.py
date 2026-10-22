"""可选真实 PostgreSQL 验证，每个测试只写入独立临时 schema。"""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import Settings
from app.core.errors import AppError
from app.models.document_embedding import DocumentEmbeddingJob
from app.models.model_configuration import MODEL_KINDS, ModelBinding, ModelProfile
from app.models.user import User, UserSession
from app.schemas.auth import AdminUserUpdate
from app.services.model_configuration import change_binding, lock_model_binding
from app.services.user_admin import delete_user, lock_admins, update_user
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
