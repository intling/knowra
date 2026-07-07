from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

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

    def shutdown(self) -> None:
        self.shutdown_calls += 1


# 测试 FastAPI lifespan 启动时会执行文档模型 bootstrap。
# 该测试驱动启动阶段写入进程内 readiness，供健康检查和任务执行读取。
def test_app_lifespan_runs_document_model_bootstrap_service() -> None:
    app = create_app(Settings(_env_file=None))
    bootstrap = FakeBootstrapService()
    app.state.document_model_bootstrap_service_factory = lambda: bootstrap

    with TestClient(app):
        pass

    assert bootstrap.calls == 1
    assert app.state.document_model_readiness.status == "skipped"


# 测试 lifespan 在文件 bootstrap 后启动非阻塞的模型内存预加载。
# 该测试驱动 app.state 保存 runtime readiness，而不是仅保存文件 readiness。
def test_app_lifespan_starts_document_model_runtime_without_blocking_startup() -> None:
    app = create_app(Settings(_env_file=None))
    bootstrap_result = SimpleNamespace(status="ready")
    bootstrap = FakeBootstrapService(result=bootstrap_result)
    runtime = FakeRuntime()
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
