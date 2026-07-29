# 测试进程重启时对残留 queued/running 任务的收尾（reconcile_stale_jobs_at_startup）。
# 覆盖背景：ApplicationShutdownCoordinator.shutdown() 只处理优雅关闭；进程被
# kill -9 / OOM 等非正常终止后，DB 里的 queued/running 任务永远不会被标记为
# failed，会一直挡住后续 rechunk/re-embed 的 409 冲突检查。这里验证启动阶段
# 补的同一收尾逻辑，覆盖 parse/chunk/embedding 三类作业。

from pathlib import Path

from app.core.shutdown import reconcile_stale_jobs_at_startup
from app.models.document_chunking import DocumentChunkJob
from app.models.document_embedding import DocumentEmbeddingJob
from app.models.document_parsing import DocumentParseJob
from tests.document_chunking_helpers import chunking_session, make_parsed_document_with_segment
from tests.document_parsing_helpers import SessionFactory


def test_reconcile_stale_jobs_at_startup_marks_queued_and_running_jobs_failed(
    tmp_path: Path,
) -> None:
    with chunking_session() as session:
        owner, _upload, _parse_job, parsed = make_parsed_document_with_segment(session, tmp_path)

        stuck_parse_job = DocumentParseJob(
            uploaded_file_id=_upload.id,
            owner_user_id=owner.id,
            status="running",
        )
        stuck_chunk_job = DocumentChunkJob(
            parsed_document_id=parsed.id,
            owner_user_id=owner.id,
            status="running",
        )
        session.add(stuck_parse_job)
        session.add(stuck_chunk_job)
        session.commit()
        session.refresh(stuck_chunk_job)

        stuck_embedding_job = DocumentEmbeddingJob(
            chunk_job_id=stuck_chunk_job.id,
            parsed_document_id=parsed.id,
            owner_user_id=owner.id,
            status="queued",
            model="fake-embedding-model",
            dimensions=8,
        )
        session.add(stuck_embedding_job)
        session.commit()

        # Act — 模拟应用启动时的收尾调用。
        reconcile_stale_jobs_at_startup(
            session_factory=SessionFactory(session),
            reason="startup_reconciliation",
        )

        for job in (stuck_parse_job, stuck_chunk_job, stuck_embedding_job):
            session.refresh(job)
            assert job.status == "failed"
            assert job.error_code == "process_shutdown"
            assert "startup_reconciliation" in job.error_message
            assert job.finished_at is not None


def test_reconcile_stale_jobs_at_startup_does_not_touch_finished_jobs(tmp_path: Path) -> None:
    with chunking_session() as session:
        owner, _upload, parse_job, _parsed = make_parsed_document_with_segment(session, tmp_path)
        # make_parsed_document_with_segment 已经把 parse_job 落库为 succeeded。

        reconcile_stale_jobs_at_startup(session_factory=SessionFactory(session))

        session.refresh(parse_job)
        assert parse_job.status == "succeeded"
        assert parse_job.error_code is None


def test_reconcile_stale_jobs_at_startup_swallows_session_factory_errors() -> None:
    def broken_session_factory():
        raise RuntimeError("database unreachable")

    # 收尾失败不应该阻止应用启动——记录错误并直接返回。
    reconcile_stale_jobs_at_startup(session_factory=broken_session_factory)
