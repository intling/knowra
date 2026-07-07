import signal
from collections.abc import Generator
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import Settings
from app.main import create_app
from app.services.document_model_bootstrap import DocumentModelBootstrapError


class FakeBootstrapService:
    def __init__(self, *, result=None, error: Exception | None = None) -> None:
        self.result = result or SimpleNamespace(status="skipped")
        self.error = error
        self.calls = 0

    def run(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


class FakeRuntime:
    def __init__(self) -> None:
        self.status = "loading"
        self.docling = SimpleNamespace(status="loading", missing_models=[])
        self.tokenizer = SimpleNamespace(status="loading", missing_models=[])
        self.start_calls = 0
        self.shutdown_calls = 0

    def start_async(self) -> None:
        self.start_calls += 1

    def shutdown(self, *args, **kwargs) -> None:
        self.shutdown_calls += 1


class FakeShutdownCoordinator:
    def __init__(self) -> None:
        self.shutdown_calls = 0
        self.is_shutting_down = False

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        self.is_shutting_down = True


class RecordingLogger:
    def __init__(self) -> None:
        self.events = []

    def info(self, event: str, **kwargs) -> None:
        self.events.append((event, kwargs))

    def warning(self, event: str, **kwargs) -> None:
        self.events.append((event, kwargs))

    def error(self, event: str, **kwargs) -> None:
        self.events.append((event, kwargs))


def install_isolated_shutdown_session_factory(app) -> None:
    __import__("app.models.uploaded_file")
    __import__("app.models.document_parsing")
    __import__("app.models.document_chunking")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    @contextmanager
    def session_factory() -> Generator[Session]:
        with Session(engine) as session:
            yield session

    app.state.application_shutdown_session_factory = session_factory


# 测试 FastAPI lifespan 启动时会执行文档模型 bootstrap。
# 该测试驱动启动阶段写入进程内 readiness，供健康检查和任务执行读取。
def test_app_lifespan_runs_document_model_bootstrap_service() -> None:
    app = create_app(Settings(_env_file=None))
    bootstrap = FakeBootstrapService()
    coordinator = FakeShutdownCoordinator()
    app.state.document_model_bootstrap_service_factory = lambda: bootstrap
    app.state.application_shutdown_coordinator = coordinator

    with TestClient(app):
        assert bootstrap.calls == 1
        assert app.state.document_model_readiness.status == "skipped"

    assert coordinator.shutdown_calls == 1


# 测试 lifespan 在文件 bootstrap 后启动非阻塞的模型内存预加载。
# 该测试驱动 app.state 保存 runtime readiness，而不是仅保存文件 readiness。
def test_app_lifespan_starts_document_model_runtime_without_blocking_startup() -> None:
    app = create_app(Settings(_env_file=None))
    bootstrap_result = SimpleNamespace(status="ready")
    bootstrap = FakeBootstrapService(result=bootstrap_result)
    runtime = FakeRuntime()
    install_isolated_shutdown_session_factory(app)
    app.state.document_model_bootstrap_service_factory = lambda: bootstrap
    app.state.document_model_runtime_factory = lambda readiness: runtime

    with TestClient(app):
        assert bootstrap.calls == 1
        assert runtime.start_calls == 1
        assert app.state.document_model_readiness is runtime

    assert runtime.shutdown_calls == 1


# 测试 fail_fast 语义会在 lifespan 阶段中止应用启动。
# 该测试确保模型不可用时不会在生产启动后才暴露问题。
def test_app_lifespan_propagates_document_model_bootstrap_error() -> None:
    app = create_app(Settings(_env_file=None))
    bootstrap = FakeBootstrapService(
        error=DocumentModelBootstrapError("Document models are unavailable: layout")
    )
    app.state.document_model_bootstrap_service_factory = lambda: bootstrap

    with pytest.raises(DocumentModelBootstrapError, match="layout"), TestClient(app):
        pass


# 测试 lifespan teardown 会调用统一 shutdown coordinator，且不覆盖 ASGI server signal handler。
# 该测试驱动 Ctrl+C/SIGTERM 由 server 进入 lifespan teardown，而不是业务层抢占 signal。
def test_app_lifespan_uses_shutdown_coordinator_without_replacing_signal_handler() -> None:
    original_handler = signal.getsignal(signal.SIGINT)
    app = create_app(Settings(_env_file=None))
    bootstrap = FakeBootstrapService()
    runtime = FakeRuntime()
    coordinator = FakeShutdownCoordinator()
    app.state.document_model_bootstrap_service_factory = lambda: bootstrap
    app.state.document_model_runtime_factory = lambda readiness: runtime
    app.state.application_shutdown_coordinator = coordinator

    with TestClient(app):
        assert signal.getsignal(signal.SIGINT) is original_handler

    assert signal.getsignal(signal.SIGINT) is original_handler
    assert coordinator.shutdown_calls == 1
    assert coordinator.is_shutting_down is True


# 测试 graceful shutdown 输出稳定结构化日志事件，便于定位停止和清理结果。
# 该测试保护关闭路径与普通模型 runtime shutdown 区分开来。
def test_app_lifespan_logs_graceful_shutdown_events(monkeypatch) -> None:
    from app.core import shutdown as shutdown_module

    logger = RecordingLogger()
    monkeypatch.setattr(shutdown_module, "logger", logger)
    app = create_app(Settings(_env_file=None))
    install_isolated_shutdown_session_factory(app)
    app.state.document_model_bootstrap_service_factory = lambda: FakeBootstrapService()

    with TestClient(app):
        pass

    messages = [event for event, _fields in logger.events]
    assert "Application graceful shutdown started" in messages
    assert "Application graceful shutdown completed" in messages
