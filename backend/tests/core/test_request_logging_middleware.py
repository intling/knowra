import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.middleware import RequestLoggingMiddleware


def test_request_logging_middleware_logs_request_completion_at_debug(caplog) -> None:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/probe")
    def probe() -> dict[str, str]:
        return {"status": "ok"}

    caplog.set_level(logging.DEBUG)

    response = TestClient(app).get("/probe")

    assert response.status_code == 200
    request_records = [
        record
        for record in caplog.records
        if record.name == "app.http" and "HTTP request completed" in record.getMessage()
    ]
    assert request_records
    assert all(record.levelno == logging.DEBUG for record in request_records)
    assert any("'method': 'GET'" in record.getMessage() for record in request_records)
    assert any("'path': '/probe'" in record.getMessage() for record in request_records)
    assert any("'status_code': 200" in record.getMessage() for record in request_records)
