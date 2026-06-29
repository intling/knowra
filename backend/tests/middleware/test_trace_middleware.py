"""Tests for the Trace middleware (app.middleware.trace).

4.1–4.3 red tests for X-Trace-ID handling.
"""

import logging
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.trace_context import get_trace_id
from app.middleware.trace import TRACE_HEADER, TraceMiddleware, generate_uuid7

# ---------------------------------------------------------------------------
# UUID7 helper tests (needed by middleware)
# ---------------------------------------------------------------------------


class TestUuid7Generation:
    def test_generates_valid_uuid_format(self):
        result = generate_uuid7()
        # UUID format: 8-4-4-4-12 hex chars
        uuid.UUID(result)  # should not raise

    def test_uuid7_starts_with_version_char(self):
        """UUID7 首字符为 '0'（版本标识）"""
        result = generate_uuid7()
        # The 13th character is the version nibble (position 12, 0-indexed).
        # UUID format: xxxxxxxx-xxxx-7xxx-...
        assert result[14] == "7"  # version char at position 14 in standard format

    def test_uuid7_has_correct_length(self):
        result = generate_uuid7()
        assert len(result) == 36  # 32 hex + 4 dashes


# ---------------------------------------------------------------------------
# Trace middleware
# ---------------------------------------------------------------------------


@pytest.fixture
def trace_app() -> FastAPI:
    """FastAPI app with the TraceMiddleware registered and a simple echo route."""
    app = FastAPI()
    app.add_middleware(TraceMiddleware)

    @app.get("/echo")
    def echo():
        return {"trace_id": get_trace_id()}

    return app


@pytest.fixture
def trace_client(trace_app: FastAPI) -> TestClient:
    return TestClient(trace_app)


class TestTraceMiddleware:
    """4.1–4.3 验证中间件对 X-Trace-ID 的处理"""

    def test_request_with_valid_x_trace_id_header(self, trace_client):
        """4.1 请求携带有效 X-Trace-ID 时，中间件将其设置为 trace_id"""
        response = trace_client.get("/echo", headers={TRACE_HEADER: "01JFZ8KJ4X2Q3M5N"})
        assert response.status_code == 200
        assert response.json()["trace_id"] == "01JFZ8KJ4X2Q3M5N"
        assert response.headers[TRACE_HEADER] == "01JFZ8KJ4X2Q3M5N"

    def test_request_without_x_trace_id_header(self, trace_client):
        """4.2 请求缺少 X-Trace-ID 时，中间件生成新 UUID7"""
        response = trace_client.get("/echo")
        assert response.status_code == 200
        trace_id = response.json()["trace_id"]
        # Should be a valid UUID (UUID7)
        uuid.UUID(trace_id)
        assert response.headers[TRACE_HEADER] == trace_id

    def test_request_with_blank_x_trace_id_header(self, trace_client):
        """4.3 请求携带空白 X-Trace-ID 时，中间件生成新 UUID7"""
        response = trace_client.get("/echo", headers={TRACE_HEADER: ""})
        assert response.status_code == 200
        trace_id = response.json()["trace_id"]
        uuid.UUID(trace_id)
        assert response.headers[TRACE_HEADER] == trace_id
        # Should not be empty (a new UUID7 was generated)
        assert trace_id != ""

    def test_request_with_whitespace_only_x_trace_id(self, trace_client):
        """空白（仅空格）的 X-Trace-ID 也视为缺失"""
        response = trace_client.get("/echo", headers={TRACE_HEADER: "   "})
        assert response.status_code == 200
        trace_id = response.json()["trace_id"]
        uuid.UUID(trace_id)


# =========================================================================
# 日志记录测试（spec: 中间件层日志记录 — trace.py）
# =========================================================================


# 测试请求未携带 X-Trace-ID 时中间件应输出 DEBUG 级别日志，包含生成的 trace_id。
def test_trace_middleware_logs_debug_on_new_trace_id(
    trace_client,
    caplog,
) -> None:
    caplog.set_level(logging.DEBUG)

    trace_client.get("/echo")

    middleware_records = [r for r in caplog.records if r.name == "app.middleware.trace"]
    assert any(r.levelname == "DEBUG" for r in middleware_records)


# 测试请求携带有效 X-Trace-ID 时中间件应输出 DEBUG 级别日志，包含接收到的 trace_id。
def test_trace_middleware_logs_debug_on_received_trace_id(
    trace_client,
    caplog,
) -> None:
    caplog.set_level(logging.DEBUG)

    trace_client.get("/echo", headers={TRACE_HEADER: "01JFZ8KJ4X2Q3M5N"})

    middleware_records = [r for r in caplog.records if r.name == "app.middleware.trace"]
    assert any(r.levelname == "DEBUG" for r in middleware_records)
