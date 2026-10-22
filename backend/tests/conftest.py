from collections.abc import Generator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.shutdown import ApplicationShutdownState
from app.main import app
from app.services.document_model_bootstrap import skipped_readiness


@contextmanager
def empty_shutdown_session_factory() -> Generator[Session]:
    __import__("app.models.uploaded_file")
    __import__("app.models.document_parsing")
    __import__("app.models.document_chunking")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(autouse=True)
def skip_document_model_bootstrap_for_global_app():
    app.state.document_model_readiness = skipped_readiness()
    app.state.document_model_bootstrap_service_factory = lambda: type(
        "SkippedBootstrap",
        (),
        {"run": staticmethod(skipped_readiness)},
    )()
    app.state.application_shutdown_state = ApplicationShutdownState()
    app.state.application_shutdown_coordinator = None
    app.state.application_shutdown_session_factory = empty_shutdown_session_factory
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def db_session() -> Generator[Session]:
    """Provide a real SQLite session for the dependency override."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as test_session:
        yield test_session


# ── 用户体系测试共享 fixture ─────────────────────────────────────────────


@pytest.fixture
def fast_password_hasher(monkeypatch):
    """测试使用低成本 argon2id 参数，避免每次哈希耗时数十毫秒。"""
    from argon2 import PasswordHasher

    from app.services import passwords

    monkeypatch.setattr(
        passwords, "_hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    )


@pytest.fixture
def auth_db() -> Generator[Session]:
    """导入全部业务模型的内存 SQLite，会话供认证与隔离测试共享。"""
    from tests.auth_helpers import make_sqlite_session

    yield from make_sqlite_session()


@pytest.fixture
def auth_client(auth_db: Session, fast_password_hasher) -> Generator[TestClient]:
    """走真实认证链路的客户端：只覆盖数据库会话与登录限流器。"""
    from app.api.deps import get_login_rate_limiter
    from app.services.auth import LoginRateLimiter

    from tests.auth_helpers import override_db

    limiter = LoginRateLimiter(max_failures=5, window_seconds=900)
    override_db(auth_db)
    app.dependency_overrides[get_login_rate_limiter] = lambda: limiter
    with TestClient(app) as test_client:
        test_client.login_rate_limiter = limiter
        yield test_client
    app.dependency_overrides.clear()
