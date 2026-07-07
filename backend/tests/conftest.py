import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.document_model_bootstrap import skipped_readiness


@pytest.fixture(autouse=True)
def skip_document_model_bootstrap_for_global_app():
    app.state.document_model_readiness = skipped_readiness()
    app.state.document_model_bootstrap_service_factory = lambda: type(
        "SkippedBootstrap",
        (),
        {"run": staticmethod(skipped_readiness)},
    )()
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
