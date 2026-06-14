import logging
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.request_context import request_id_var

logger = logging.getLogger("app.http")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request with method, path, status code, and duration.

    A short ``request_id`` is attached to ``request.state.request_id`` and
    stored in a :mod:`contextvars` slot so downstream services can reference it.
    """

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        request_id = str(uuid4())[:8]
        request.state.request_id = request_id  # type: ignore[attr-defined]
        token = request_id_var.set(request_id)

        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)

        duration_ms = (time.perf_counter() - start) * 1000
        status_code = getattr(response, "status_code", 500)
        logger.info(
            "%s %s → %d (%.1fms)",
            request.method,
            request.url.path,
            status_code,
            duration_ms,
        )
        return response
