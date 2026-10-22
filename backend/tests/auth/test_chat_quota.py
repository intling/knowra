"""演示问答额度红测试：滚动窗口、失败释放、持久化与并发。"""

import importlib
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, create_engine, select

from app.core.errors import AppError
from app.models.user import User
from tests.auth_helpers import make_account

NOW = datetime(2026, 10, 21, 8, 15, tzinfo=UTC)


def quota_types():
    # 延迟导入，RED 时明确指出尚不存在的领域模型与服务，不阻止其他测试收集。
    models = importlib.import_module("app.models.chat_quota")
    service = importlib.import_module("app.services.chat_quota")
    return models.UserChatLimit, models.ChatUsage, service


def limited_user(session: Session, *, limit: int = 3):
    limit_model, _, _ = quota_types()
    user = make_account(session)
    session.add(limit_model(user_id=user.id, hourly_limit=limit))
    session.commit()
    return user


# 验证前 3 次可预留且第 4 次返回可读 429、稳定错误码和精确重试秒数。
def test_three_reservations_then_reject_with_retry_after(auth_db, fast_password_hasher):
    _, usage_model, service = quota_types()
    user = limited_user(auth_db)
    reservations = [service.reserve_chat(auth_db, user.id, now=NOW) for _ in range(3)]

    assert len(set(reservations)) == 3
    assert None not in reservations
    with pytest.raises(AppError) as error:
        service.reserve_chat(auth_db, user.id, now=NOW + timedelta(seconds=10))

    assert error.value.status_code == 429
    assert error.value.code == "chat_quota_exceeded"
    assert "3" in error.value.detail and "稍后" in error.value.detail
    assert int(error.value.headers["Retry-After"]) == 3590
    assert len(auth_db.exec(select(usage_model)).all()) == 3


# 验证没有配置额度的普通成员和管理员均不受演示次数影响，也不创建使用记录。
@pytest.mark.parametrize("role", ["member", "admin"])
def test_unconfigured_accounts_are_unlimited(auth_db, fast_password_hasher, role):
    _, usage_model, service = quota_types()
    user = make_account(auth_db, role=role)

    for _ in range(5):
        assert service.reserve_chat(auth_db, user.id, now=NOW) is None

    assert auth_db.exec(select(usage_model)).all() == []


# 验证独立账号拥有独立额度，不能被另一个演示账号的成功记录消耗。
def test_account_quotas_are_independent(auth_db, fast_password_hasher):
    _, _, service = quota_types()
    first, second = limited_user(auth_db), limited_user(auth_db)
    for _ in range(3):
        service.reserve_chat(auth_db, first.id, now=NOW)

    assert service.reserve_chat(auth_db, second.id, now=NOW) is not None


# 验证滚动时间边界：3599.5 秒仍占用，满 3600 秒释放，Retry-After 向上取整。
def test_rolling_window_expires_at_exact_hour(auth_db, fast_password_hasher):
    _, _, service = quota_types()
    user = limited_user(auth_db)
    service.reserve_chat(auth_db, user.id, now=NOW)
    service.reserve_chat(auth_db, user.id, now=NOW + timedelta(seconds=20))
    service.reserve_chat(auth_db, user.id, now=NOW + timedelta(seconds=30))

    with pytest.raises(AppError) as error:
        service.reserve_chat(auth_db, user.id, now=NOW + timedelta(seconds=3599.5))
    assert error.value.headers["Retry-After"] == "1"
    assert service.reserve_chat(auth_db, user.id, now=NOW + timedelta(hours=1)) is not None
    with pytest.raises(AppError) as error:
        service.reserve_chat(auth_db, user.id, now=NOW + timedelta(hours=1, seconds=1))
    assert error.value.status_code == 429
    assert int(error.value.headers["Retry-After"]) == 19


# 验证释放一个失败请求只恢复一个额度，其他在途请求仍占用并发额度。
def test_failed_request_releases_only_its_own_reservation(auth_db, fast_password_hasher):
    _, usage_model, service = quota_types()
    user = limited_user(auth_db)
    reservations = [service.reserve_chat(auth_db, user.id, now=NOW) for _ in range(3)]

    service.release_chat(auth_db, reservations[0])
    service.release_chat(auth_db, reservations[0])
    assert service.reserve_chat(auth_db, user.id, now=NOW) is not None
    with pytest.raises(AppError, match="."):
        service.reserve_chat(auth_db, user.id, now=NOW)
    assert len(auth_db.exec(select(usage_model)).all()) == 3


# 验证不限额请求清理时可传入 None，不能误删其他账号的使用记录。
def test_releasing_unlimited_request_is_noop(auth_db, fast_password_hasher):
    _, usage_model, service = quota_types()
    user = limited_user(auth_db)
    service.reserve_chat(auth_db, user.id, now=NOW)

    service.release_chat(auth_db, None)

    assert len(auth_db.exec(select(usage_model)).all()) == 1


# 验证新数据库连接继续读取已提交额度，模拟重新登录、多进程与服务重启。
def test_usage_survives_new_database_session(auth_db, fast_password_hasher):
    _, _, service = quota_types()
    user = limited_user(auth_db)
    user_id = user.id
    for _ in range(3):
        service.reserve_chat(auth_db, user_id, now=NOW)

    with Session(auth_db.get_bind()) as fresh_session:
        with pytest.raises(AppError) as error:
            service.reserve_chat(fresh_session, user_id, now=NOW)
        assert error.value.code == "chat_quota_exceeded"


# 验证数据库自身拒绝 0 和负数额度，不能只依赖 CLI 的参数校验。
@pytest.mark.parametrize("limit", [0, -1])
def test_database_rejects_nonpositive_hourly_limit(auth_db, fast_password_hasher, limit):
    limit_model, _, _ = quota_types()
    user = make_account(auth_db)
    auth_db.add(limit_model(user_id=user.id, hourly_limit=limit))

    with pytest.raises(IntegrityError):
        auth_db.commit()
    auth_db.rollback()


# 验证 PostgreSQL 多连接并发下最多放行 3 个请求；使用独立 schema 并完整清理。
def test_postgres_concurrent_requests_cannot_exceed_limit():
    database_url = os.environ.get("CHAT_QUOTA_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("需显式提供隔离恢复库连接，验证 PostgreSQL FOR UPDATE 多连接并发")
    limit_model, usage_model, service = quota_types()
    schema = "quota_verification_" + uuid4().hex
    base_engine = create_engine(database_url)
    with base_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_engine = base_engine.execution_options(schema_translate_map={None: schema})
    try:
        User.metadata.create_all(
            scoped_engine, tables=[User.__table__, limit_model.__table__, usage_model.__table__]
        )
        with Session(scoped_engine) as session:
            user = User(display_name="quota concurrency fixture")
            session.add(user)
            session.commit()
            user_id = user.id
            session.add(limit_model(user_id=user_id, hourly_limit=3))
            session.commit()

        barrier = Barrier(8)

        def attempt(_):
            # 同步起跑，确保测试真实竞争配置行锁，而不是串行计数。
            with Session(scoped_engine) as session:
                barrier.wait(timeout=10)
                try:
                    service.reserve_chat(session, user_id, now=NOW)
                    return 200
                except AppError as error:
                    assert error.code == "chat_quota_exceeded"
                    return error.status_code

        with ThreadPoolExecutor(max_workers=8) as executor:
            statuses = list(executor.map(attempt, range(8)))
        assert statuses.count(200) == 3, "并发额度必须恰好放行 3 个请求"
        assert statuses.count(429) == 5, "其他并发请求必须在模型调用前拒绝"
        with Session(scoped_engine) as session:
            assert len(session.exec(select(usage_model)).all()) == 3
    finally:
        with base_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        scoped_engine.dispose()
        base_engine.dispose()
