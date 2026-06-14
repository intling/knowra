"""Lightweight request-scoped context for correlation IDs.

Uses :mod:`contextvars` so the request ID flows transparently across
async boundaries without threading through every function signature.
"""

from contextvars import ContextVar
from uuid import uuid4

request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    """Return the current request ID, generating a short one if absent."""
    rid = request_id_var.get()
    if not rid:
        rid = str(uuid4())[:8]
    return rid
