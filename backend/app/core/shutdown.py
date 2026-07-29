from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session

from app.core.logging import get_logger
from app.db.session import engine
from app.models.user import utc_now
from app.services.document_chunking import mark_incomplete_chunk_jobs_failed_for_shutdown
from app.services.document_embedding import mark_incomplete_embedding_jobs_failed_for_shutdown
from app.services.document_parse_dispatcher import mark_incomplete_parse_jobs_failed_for_shutdown

logger = get_logger(__name__)
ShutdownSessionFactory = Callable[[], Generator[Session]]


@contextmanager
def default_shutdown_session_factory() -> Generator[Session]:
    with Session(engine) as session:
        yield session


def reconcile_stale_jobs_at_startup(
    *,
    session_factory: ShutdownSessionFactory = default_shutdown_session_factory,
    reason: str = "startup_reconciliation",
) -> None:
    """应用启动时，把上一次运行遗留的 queued/running 任务标记为 failed。

    ``ApplicationShutdownCoordinator.shutdown()`` 只覆盖优雅关闭路径；进程被
    kill -9 / OOM / 断电等非正常终止时，DB 里的 queued/running 任务永远不会
    被标记，会一直挡住后续 rechunk/re-embed 的 409 冲突检查。这里在应用启动
    时补一次同样的收尾，复用与 shutdown 完全相同的标记函数。收尾本身失败（如 DB
    不可达）不应阻止应用启动，只记录错误日志并返回。
    """
    try:
        with session_factory() as session:
            parse_jobs = mark_incomplete_parse_jobs_failed_for_shutdown(
                session=session, reason=reason
            )
            chunk_jobs = mark_incomplete_chunk_jobs_failed_for_shutdown(
                session=session, reason=reason
            )
            embedding_jobs = mark_incomplete_embedding_jobs_failed_for_shutdown(
                session=session, reason=reason
            )
    except Exception as exc:
        logger.error(
            "Startup job reconciliation failed",
            reason=reason,
            error=str(exc),
            exc_info=True,
        )
        return

    logger.info(
        "Startup job reconciliation completed",
        reason=reason,
        parse_jobs=parse_jobs,
        chunk_jobs=chunk_jobs,
        embedding_jobs=embedding_jobs,
    )


@dataclass
class ApplicationShutdownState:
    is_shutting_down: bool = False
    started_at: datetime | None = None
    reason: str | None = None

    def begin(self, *, reason: str = "lifespan_teardown") -> bool:
        if self.is_shutting_down:
            return False

        self.is_shutting_down = True
        self.started_at = utc_now()
        self.reason = reason
        return True


class ApplicationShutdownCoordinator:
    def __init__(
        self,
        *,
        app,
        shutdown_state: ApplicationShutdownState,
        model_shutdown_timeout_seconds: float,
        session_factory: ShutdownSessionFactory = default_shutdown_session_factory,
    ) -> None:
        self.app = app
        self.shutdown_state = shutdown_state
        self.model_shutdown_timeout_seconds = model_shutdown_timeout_seconds
        self.session_factory = session_factory
        self._completed = False

    def shutdown(self, *, reason: str = "lifespan_teardown") -> None:
        first_call = self.shutdown_state.begin(reason=reason)
        if self._completed:
            logger.info("Application graceful shutdown already completed", reason=reason)
            return

        logger.info(
            "Application graceful shutdown started",
            reason=self.shutdown_state.reason,
            first_call=first_call,
        )
        runtime = getattr(self.app.state, "document_model_readiness", None)
        if hasattr(runtime, "shutdown"):
            runtime.shutdown(timeout_seconds=self.model_shutdown_timeout_seconds)

        parse_jobs = 0
        chunk_jobs = 0
        embedding_jobs = 0
        try:
            with self.session_factory() as session:
                parse_jobs = mark_incomplete_parse_jobs_failed_for_shutdown(
                    session=session,
                    reason=str(self.shutdown_state.reason or reason),
                )
                chunk_jobs = mark_incomplete_chunk_jobs_failed_for_shutdown(
                    session=session,
                    reason=str(self.shutdown_state.reason or reason),
                )
                embedding_jobs = mark_incomplete_embedding_jobs_failed_for_shutdown(
                    session=session,
                    reason=str(self.shutdown_state.reason or reason),
                )
        except Exception as exc:
            logger.error(
                "Application graceful shutdown job cleanup failed",
                reason=self.shutdown_state.reason,
                error=str(exc),
                exc_info=True,
            )

        self._completed = True
        logger.info(
            "Application graceful shutdown completed",
            reason=self.shutdown_state.reason,
            parse_jobs=parse_jobs,
            chunk_jobs=chunk_jobs,
            embedding_jobs=embedding_jobs,
        )
