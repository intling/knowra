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
