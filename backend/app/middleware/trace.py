"""FastAPI middleware that reads / issues ``X-Trace-ID`` for every request."""

from __future__ import annotations

import os
import time
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.trace_context import set_trace_id

TRACE_HEADER = "X-Trace-ID"

# Expose as a callable for testability.
RequestResponseEndpoint = Callable[[Request], Response]


def generate_uuid7() -> str:
    """Return a UUID7 string (time-ordered, per draft RFC 9562)."""
    ts_ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF  # 48 bits
    rand_bytes = os.urandom(10)  # 80 bits of randomness

    # Build the 128-bit UUID manually.
    # bytes 0-5: 48-bit unix timestamp (big-endian)
    ts_bytes = ts_ms.to_bytes(6, "big")

    # byte 6: 4 bits version (7) + 4 high bits of rand_a
    ver_byte = 0x70 | (rand_bytes[0] & 0x0F)

    # byte 7: 8 bits of rand_a
    rand_a_lo = rand_bytes[1]

    # byte 8: 2 bits variant (10xx) + 6 high bits of rand_b
    var_byte = 0x80 | (rand_bytes[2] & 0x3F)

    # bytes 9-15: the rest of rand_b
    rand_b_rest = rand_bytes[3:10]

    uuid_bytes = ts_bytes + bytes([ver_byte, rand_a_lo, var_byte]) + rand_b_rest

    # Format: 8-4-4-4-12 hex
    h = uuid_bytes.hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


class TraceMiddleware(BaseHTTPMiddleware):
    """Read ``X-Trace-ID`` from the request, issue one if missing, and inject
    it into the response header and trace context."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        trace_id = (request.headers.get(TRACE_HEADER, "")).strip()
        if not trace_id:
            trace_id = generate_uuid7()

        set_trace_id(trace_id)

        response = await call_next(request)
        response.headers[TRACE_HEADER] = trace_id
        return response
