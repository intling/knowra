"""Integration tests for the full trace-id → logger chain.

5.2 验证从请求进入到响应的完整日志链路。
"""

import logging

import structlog
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.logging import TraceFilter, _trace_id_injector, get_logger
from app.core.trace_context import get_trace_id
from app.middleware.trace import TRACE_HEADER, TraceMiddleware

# Configure structlog minimally for integration tests — no file handlers,
# just the processor chain. caplog captures stdlib output which is what
# structlog's stdlib LoggerFactory produces.
structlog.configure(
    processors=[
        _trace_id_injector,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_logger_name,
        structlog.processors.format_exc_info,
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

# Add TraceFilter to root so third-party (non-structlog) log records get trace_id.
logging.getLogger().addFilter(TraceFilter())


def _make_test_app() -> FastAPI:
    """Create a minimal FastAPI app with the TraceMiddleware and a diagnostic route."""
    app = FastAPI()
    app.add_middleware(TraceMiddleware)

    logger = get_logger("tests.integration")

    @app.get("/ping")
    def ping():
        logger.info("ping-called")
        return {"trace_id": get_trace_id()}

    return app


class TestEndToEndTraceLoggingIntegration:
    """5.2 完整链路集成测试"""

    def test_full_trace_id_chain_with_caplog(self, caplog):
        """验证 X-Trace-ID → TraceContext → logger 输出 的完整链路"""
        caplog.set_level(logging.INFO)
        client = TestClient(_make_test_app())

        response = client.get("/ping", headers={TRACE_HEADER: "integration-test-trace-id"})
        assert response.status_code == 200
        assert response.json()["trace_id"] == "integration-test-trace-id"
        assert response.headers[TRACE_HEADER] == "integration-test-trace-id"

        # With structlog, caplog records contain the event dict as the message.
        # Verify the log exists by checking the rendered log text.
        assert "integration-test-trace-id" in caplog.text
        assert "ping-called" in caplog.text

    def test_missing_trace_id_generates_new_one_with_caplog(self, caplog):
        """未携带 X-Trace-ID 时生成新的 UUID7 并注入到日志"""
        caplog.set_level(logging.INFO)
        client = TestClient(_make_test_app())

        response = client.get("/ping")
        trace_id = response.json()["trace_id"]
        assert response.headers[TRACE_HEADER] == trace_id
        # trace_id should not be the placeholder
        assert trace_id != "-"

        # The generated trace_id should appear in the log output.
        assert trace_id in caplog.text
        assert "ping-called" in caplog.text

    def test_x_trace_id_in_response_on_health_check(self):
        """响应头包含 X-Trace-ID（健康检查路由）"""
        from app.main import app

        client = TestClient(app)
        response = client.get("/api/health")
        assert "X-Trace-ID" in response.headers
