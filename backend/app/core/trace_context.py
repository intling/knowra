"""Request-scoped trace ID storage backed by contextvars.

Each asyncio Task gets its own copy of the trace ID, so concurrent
requests are automatically isolated without locking.
"""

from contextvars import ContextVar

_trace_id: ContextVar[str] = ContextVar("trace_id", default="-")


def set_trace_id(trace_id: str) -> None:
    """Store *trace_id* for the current request context."""
    _trace_id.set(trace_id)


def get_trace_id() -> str:
    """Return the trace ID for the current request context, or ``"-"``."""
    return _trace_id.get()


def clear_trace_id() -> None:
    """Reset the trace ID to the default placeholder (``"-"``)."""
    _trace_id.set("-")
