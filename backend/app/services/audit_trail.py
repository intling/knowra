"""Structured audit logging for query rewriting operations.

Emits structured audit events through structlog. All keyword arguments
passed to ``record()`` are serialized as structured fields in the log
output, enabling downstream analysis of rewrite quality, latency, and
cache effectiveness.

Usage::

    audit = AuditTrail()
    trace_id = audit.generate_id()
    audit.record(
        "query_rewrite_complete",
        trace_id=trace_id,
        original_query="如何优化 JVM 参数",
        query_hash="a1b2c3d4e5f6a7b8",
        strategies_executed=["context_fusion", "normalize"],
        total_rewrite_time_ms=450.0,
    )
"""

import uuid

from app.core.logging import get_logger


class AuditTrail:
    """Records structured audit events for query rewriting operations.

    Uses structlog for output — all keyword arguments to ``record()``
    become structured fields in the log event.  No database persistence;
    audit data exists solely in the application log stream.

    Provides ``generate_id()`` to create unique trace IDs for end-to-end
    request tracking across cache, rewrite, and search pipelines.
    """

    def __init__(self) -> None:
        self._logger = get_logger(__name__)

    @staticmethod
    def generate_id() -> str:
        """Generate a unique trace ID for end-to-end audit tracking.

        Returns a 16-character hex string derived from a UUID4,
        suitable for use as ``trace_id`` / ``audit_trail_id``
        in log events and API responses.
        """
        return uuid.uuid4().hex[:16]

    def record(self, event: str, **fields: object) -> None:
        """Emit a structured audit log event.

        Args:
            event: Fixed event name (e.g. ``"query_rewrite_complete"``).
            **fields: Arbitrary keyword arguments recorded as structured
                fields alongside the event.
        """
        self._logger.info(event, **fields)
