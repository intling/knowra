# 本文件验证 DocumentChunkingService 的核心业务语义。
# 覆盖初次分块、失败状态、segment 不变性、重分块冲突和旧作业 supersede 时机。

from importlib import import_module
from types import SimpleNamespace

from sqlmodel import select

from tests.document_chunking_helpers import (
    ChunkFixture,
    chunking_session,
    make_minimal_docling_document,
    make_parsed_document_with_segment,
)


class FakeChunker:
    # 提供可控的 fake 分块输出或错误。
    # 服务测试用它隔离 Docling SDK，只验证作业状态和 chunk 落库。
    def __init__(self, chunks=None, error: Exception | None = None) -> None:
        self.chunks = chunks or [
            ChunkFixture(
                text="Semantic retrieval should preserve source structure.",
                contextualized_text=(
                    "Course Notes > Retrieval\nSemantic retrieval should preserve source structure."
                ),
                heading_path=["Course Notes", "Retrieval"],
                page_numbers=[1],
                source_segment_indices=[0],
                metadata={"docling_ref": "#/texts/0"},
            )
        ]
        self.error = error
        self.calls = []

    # 记录服务传入的 transient 文档，并按测试场景返回 chunk 或抛错。
    # 用于验证服务的成功和失败分支。
    def chunk(self, document):
        self.calls.append(document)
        if self.error is not None:
            raise self.error
        return self.chunks


class ShutdownState:
    def __init__(self, *, is_shutting_down: bool = True) -> None:
        self.is_shutting_down = is_shutting_down
        self.reason = "signal"


# 装配使用内存 session、临时 artifact 目录和 fake chunker 的服务实例。
# 每个测试通过它专注验证分块业务行为。
def make_service(module, session, tmp_path, chunker=None):
    storage_module = import_module("app.services.document_chunk_storage")
    return module.DocumentChunkingService(
        session=session,
        chunker=chunker or FakeChunker(),
        artifact_storage=storage_module.ChunkArtifactStorage(tmp_path / "chunks"),
        config=module.DocumentChunkingConfig(
            tokenizer_model="Qwen/Qwen2-7B",
            max_tokens=512,
            merge_peers=True,
            repeat_table_header=True,
            inline_text_max_bytes=2048,
        ),
    )


# 初次分块应调用 chunker，创建 succeeded 作业，保存 chunk 关联字段。
# 测试还确认本次分块配置被持久化为作业快照。
def test_document_chunking_service_creates_job_saves_chunks_and_snapshots_config(tmp_path) -> None:
    module = import_module("app.services.document_chunking")
    models = import_module("app.models.document_chunking")
    with chunking_session() as session:
        _user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session,
            tmp_path / "uploads",
        )
        docling_document = make_minimal_docling_document()
        chunker = FakeChunker()
        service = make_service(module, session, tmp_path, chunker=chunker)

        job = service.run_initial_chunking(
            parsed_document=parsed_document,
            transient_docling_document=docling_document,
        )

        stored_job = session.get(models.DocumentChunkJob, job.id)
        chunks = session.exec(select(models.DocumentChunk)).all()
        assert chunker.calls == [docling_document]
        assert stored_job.status == "succeeded"
        assert stored_job.chunk_count == 1
        assert stored_job.chunk_config_json == {
            "tokenizer_model": "Qwen/Qwen2-7B",
            "max_tokens": 512,
            "merge_peers": True,
            "repeat_table_header": True,
            "inline_text_max_bytes": 2048,
        }
        assert chunks[0].sequence_index == 0
        assert chunks[0].parsed_document_id == parsed_document.id
        assert chunks[0].heading_path == ["Course Notes", "Retrieval"]
        assert chunks[0].page_numbers == [1]
        assert chunks[0].source_segment_indices == [0]


# 缺少 transient DoclingDocument 时，初次分块应创建 failed 作业。
# 测试确认错误码为 missing_docling_document，避免回读持久化 docling.json。
def test_document_chunking_service_fails_job_when_transient_docling_document_missing(
    tmp_path,
) -> None:
    module = import_module("app.services.document_chunking")
    models = import_module("app.models.document_chunking")
    with chunking_session() as session:
        _user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session,
            tmp_path / "uploads",
        )
        service = make_service(module, session, tmp_path)

        job = service.run_initial_chunking(
            parsed_document=parsed_document,
            transient_docling_document=None,
        )

        stored_job = session.get(models.DocumentChunkJob, job.id)
        assert stored_job.status == "failed"
        assert stored_job.error_code == "missing_docling_document"
        assert "memory document object" in stored_job.error_message


# 分块保存只应新增 document_chunks，不应改写解析阶段产出的 document_segments。
# 这个测试保护解析结果的可追溯性。
def test_document_chunking_service_does_not_modify_document_segments(tmp_path) -> None:
    module = import_module("app.services.document_chunking")
    parsing_models = import_module("app.models.document_parsing")
    with chunking_session() as session:
        _user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session,
            tmp_path / "uploads",
        )
        before = session.exec(select(parsing_models.DocumentSegment)).all()
        service = make_service(module, session, tmp_path)

        service.run_initial_chunking(
            parsed_document=parsed_document,
            transient_docling_document=make_minimal_docling_document(),
        )

        after = session.exec(select(parsing_models.DocumentSegment)).all()
        assert [(segment.id, segment.text) for segment in after] == [
            (segment.id, segment.text) for segment in before
        ]


# 同一解析结果已有 running 作业时，_get_running_job 应能返回该作业。
# 冲突检测已移至 API 层（见 test_document_chunking.py 中的 409 测试）。
def test_get_running_job_returns_active_job(tmp_path) -> None:
    module = import_module("app.services.document_chunking")
    models = import_module("app.models.document_chunking")
    with chunking_session() as session:
        user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session,
            tmp_path / "uploads",
        )
        running_job = models.DocumentChunkJob(
            parsed_document_id=parsed_document.id,
            owner_user_id=user.id,
            status="running",
            chunker_name="docling_hybrid",
            chunk_config_json={},
        )
        session.add(running_job)
        session.commit()
        service = make_service(module, session, tmp_path)

        found = service._get_running_job(parsed_document_id=parsed_document.id)
        assert found is not None
        assert found.id == running_job.id


# execute_queued_job 在成功分块后应 supersede 旧 succeeded 作业。
# 该测试验证 supersede 时机：新 chunks 写入成功后旧作业才被标记为 superseded。
def test_execute_queued_job_supersedes_old_job_after_success(tmp_path) -> None:
    module = import_module("app.services.document_chunking")
    models = import_module("app.models.document_chunking")
    with chunking_session() as session:
        user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session,
            tmp_path / "uploads",
        )
        old_job = models.DocumentChunkJob(
            parsed_document_id=parsed_document.id,
            owner_user_id=user.id,
            status="succeeded",
            chunker_name="docling_hybrid",
            chunk_config_json={},
            chunk_count=1,
        )
        session.add(old_job)
        session.commit()

        queued_job = models.DocumentChunkJob(
            parsed_document_id=parsed_document.id,
            owner_user_id=user.id,
            status="queued",
            chunker_name="docling_hybrid",
            chunk_config_json={},
        )
        session.add(queued_job)
        session.commit()
        session.refresh(queued_job)

        service = make_service(module, session, tmp_path)

        result = service.execute_queued_job(
            job=queued_job,
            parsed_document=parsed_document,
            transient_docling_document=make_minimal_docling_document(),
        )

        session.refresh(old_job)
        assert result.status == "succeeded"
        assert old_job.status == "superseded"


# 测试 shutdown 收尾会把 queued/running 分块作业标记为 process_shutdown。
# 该测试防止进程退出后分块作业永久残留并阻塞后续重分块。
def test_mark_incomplete_chunk_jobs_failed_for_shutdown_marks_only_queued_and_running(
    tmp_path,
) -> None:
    module = import_module("app.services.document_chunking")
    models = import_module("app.models.document_chunking")
    with chunking_session() as session:
        user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session,
            tmp_path / "uploads",
        )
        queued_job = models.DocumentChunkJob(
            parsed_document_id=parsed_document.id,
            owner_user_id=user.id,
            status="queued",
            chunker_name="docling_hybrid",
            chunk_config_json={},
        )
        running_job = models.DocumentChunkJob(
            parsed_document_id=parsed_document.id,
            owner_user_id=user.id,
            status="running",
            chunker_name="docling_hybrid",
            chunk_config_json={},
        )
        succeeded_job = models.DocumentChunkJob(
            parsed_document_id=parsed_document.id,
            owner_user_id=user.id,
            status="succeeded",
            chunker_name="docling_hybrid",
            chunk_config_json={},
        )
        failed_job = models.DocumentChunkJob(
            parsed_document_id=parsed_document.id,
            owner_user_id=user.id,
            status="failed",
            chunker_name="docling_hybrid",
            chunk_config_json={},
            error_code="chunking_failed",
            error_message="bad chunk",
        )
        superseded_job = models.DocumentChunkJob(
            parsed_document_id=parsed_document.id,
            owner_user_id=user.id,
            status="superseded",
            chunker_name="docling_hybrid",
            chunk_config_json={},
        )
        session.add(queued_job)
        session.add(running_job)
        session.add(succeeded_job)
        session.add(failed_job)
        session.add(superseded_job)
        session.commit()

        module.mark_incomplete_chunk_jobs_failed_for_shutdown(
            session=session,
            reason="signal",
        )

        for job in (queued_job, running_job, succeeded_job, failed_job, superseded_job):
            session.refresh(job)
        for job in (queued_job, running_job):
            assert job.status == "failed"
            assert job.error_code == "process_shutdown"
            assert "shutdown" in job.error_message.lower()
            assert job.finished_at is not None
        assert succeeded_job.status == "succeeded"
        assert succeeded_job.error_code is None
        assert failed_job.status == "failed"
        assert failed_job.error_code == "chunking_failed"
        assert failed_job.error_message == "bad chunk"
        assert superseded_job.status == "superseded"
        assert superseded_job.error_code is None


# 测试分块服务在调用 chunker 前发现 shutdown 时快速失败。
# 该测试避免关闭期继续进入 tokenizer 或 Docling HybridChunker。
def test_document_chunking_service_marks_process_shutdown_before_calling_chunker(
    tmp_path,
) -> None:
    module = import_module("app.services.document_chunking")
    models = import_module("app.models.document_chunking")
    storage_module = import_module("app.services.document_chunk_storage")
    with chunking_session() as session:
        _user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session,
            tmp_path / "uploads",
        )
        chunker = FakeChunker()
        service = module.DocumentChunkingService(
            session=session,
            chunker=chunker,
            artifact_storage=storage_module.ChunkArtifactStorage(tmp_path / "chunks"),
            config=module.DocumentChunkingConfig(),
            shutdown_state=ShutdownState(is_shutting_down=True),
        )

        job = service.run_initial_chunking(
            parsed_document=parsed_document,
            transient_docling_document=make_minimal_docling_document(),
        )

        stored_job = session.get(models.DocumentChunkJob, job.id)
        assert stored_job.status == "failed"
        assert stored_job.error_code == "process_shutdown"
        assert "shutdown" in stored_job.error_message.lower()
        assert chunker.calls == []


# 测试 chunker 生成结果后但写成功前进入 shutdown 时，作业不能被标记为 succeeded。
# 该测试保护关闭期不会留下成功误报或覆盖 process_shutdown。
def test_document_chunking_service_marks_process_shutdown_before_success_persistence(
    tmp_path,
) -> None:
    module = import_module("app.services.document_chunking")
    models = import_module("app.models.document_chunking")
    storage_module = import_module("app.services.document_chunk_storage")
    shutdown_state = ShutdownState(is_shutting_down=False)

    class ShutdownAfterChunker(FakeChunker):
        def chunk(self, document):
            chunks = super().chunk(document)
            shutdown_state.is_shutting_down = True
            return chunks

    with chunking_session() as session:
        _user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session,
            tmp_path / "uploads",
        )
        chunker = ShutdownAfterChunker()
        service = module.DocumentChunkingService(
            session=session,
            chunker=chunker,
            artifact_storage=storage_module.ChunkArtifactStorage(tmp_path / "chunks"),
            config=module.DocumentChunkingConfig(),
            shutdown_state=shutdown_state,
        )

        job = service.run_initial_chunking(
            parsed_document=parsed_document,
            transient_docling_document=make_minimal_docling_document(),
        )

        stored_job = session.get(models.DocumentChunkJob, job.id)
        assert stored_job.status == "failed"
        assert stored_job.error_code == "process_shutdown"
        assert chunker.calls != []


# ── T1.1: execute_queued_job() 单元测试 ────────────────────────────


# execute_queued_job 应对 QUEUED 作业执行分块，并 supersede 旧 succeeded 作业。
# 测试验证方法委托 _run_job 以 supersede_previous=True 模式运行。
def test_execute_queued_job_runs_with_supersede_previous_true(tmp_path) -> None:
    module = import_module("app.services.document_chunking")
    models = import_module("app.models.document_chunking")
    with chunking_session() as session:
        user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session,
            tmp_path / "uploads",
        )
        old_job = models.DocumentChunkJob(
            parsed_document_id=parsed_document.id,
            owner_user_id=user.id,
            status="succeeded",
            chunker_name="docling_hybrid",
            chunk_config_json={},
            chunk_count=1,
        )
        session.add(old_job)
        session.commit()

        queued_job = models.DocumentChunkJob(
            parsed_document_id=parsed_document.id,
            owner_user_id=user.id,
            status="queued",
            chunker_name="docling_hybrid",
            chunk_config_json={},
        )
        session.add(queued_job)
        session.commit()
        session.refresh(queued_job)

        chunker = FakeChunker()
        service = make_service(module, session, tmp_path, chunker=chunker)

        result = service.execute_queued_job(
            job=queued_job,
            parsed_document=parsed_document,
            transient_docling_document=make_minimal_docling_document(),
        )

        session.refresh(old_job)
        session.refresh(result)
        assert result.status == "succeeded"
        assert old_job.status == "superseded"
        assert chunker.calls != []


# execute_queued_job 不应创建新作业，直接使用传入的 job 参数。
# 测试验证作业总数不变，且返回的 job ID 与传入一致。
def test_execute_queued_job_does_not_create_new_job(tmp_path) -> None:
    module = import_module("app.services.document_chunking")
    models = import_module("app.models.document_chunking")
    with chunking_session() as session:
        _user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session,
            tmp_path / "uploads",
        )
        queued_job = models.DocumentChunkJob(
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status="queued",
            chunker_name="docling_hybrid",
            chunk_config_json={},
        )
        session.add(queued_job)
        session.commit()
        session.refresh(queued_job)

        job_count_before = len(session.exec(select(models.DocumentChunkJob)).all())
        service = make_service(module, session, tmp_path)

        result = service.execute_queued_job(
            job=queued_job,
            parsed_document=parsed_document,
            transient_docling_document=make_minimal_docling_document(),
        )

        job_count_after = len(session.exec(select(models.DocumentChunkJob)).all())
        assert result.id == queued_job.id
        assert job_count_after == job_count_before


# ── T1.2: run_rechunk_job 单元测试 ──────────────────────────────────


class FakeParser:
    """注入到 run_rechunk_job 的假解析器，返回可控的解析结果。"""

    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list = []

    def parse(self, path, *, document_format=None):
        self.calls.append((path, document_format))
        if self.error is not None:
            raise self.error
        if self.result is not None:
            return self.result
        return SimpleNamespace(transient_docling_document=make_minimal_docling_document())


def _make_session_factory(session):
    """将单个 SQLModel Session 包装为 run_rechunk_job 兼容的工厂。"""
    from contextlib import contextmanager

    @contextmanager
    def factory():
        yield session

    return factory


# run_rechunk_job 正常路径：加载 QUEUED job → 解析 → 分块 → SUCCEEDED。
# 测试通过注入假 parser 和 chunking_service 隔离真实 Docling 依赖。
def test_run_rechunk_job_succeeds_with_valid_queued_job(tmp_path) -> None:
    module = import_module("app.services.document_chunking")
    models = import_module("app.models.document_chunking")
    with chunking_session() as session:
        user, upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session,
            tmp_path / "uploads",
        )
        queued_job = models.DocumentChunkJob(
            parsed_document_id=parsed_document.id,
            owner_user_id=user.id,
            status="queued",
            chunker_name="docling_hybrid",
            chunk_config_json={},
        )
        session.add(queued_job)
        session.commit()
        session.refresh(queued_job)

        chunker = FakeChunker()
        service = make_service(module, session, tmp_path, chunker=chunker)
        fake_parser = FakeParser()

        module.run_rechunk_job(
            queued_job.id,
            session_factory=_make_session_factory(session),
            parser=fake_parser,
            upload_storage_root=tmp_path / "uploads",
            chunking_service=service,
        )

        session.refresh(queued_job)
        assert queued_job.status == "succeeded"
        assert chunker.calls != []
        assert len(fake_parser.calls) == 1


# 作业已非 QUEUED 时，run_rechunk_job 应幂等返回，不修改作业。
def test_run_rechunk_job_idempotent_when_job_not_queued(tmp_path) -> None:
    module = import_module("app.services.document_chunking")
    models = import_module("app.models.document_chunking")
    with chunking_session() as session:
        user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session,
            tmp_path / "uploads",
        )
        succeeded_job = models.DocumentChunkJob(
            parsed_document_id=parsed_document.id,
            owner_user_id=user.id,
            status="succeeded",
            chunker_name="docling_hybrid",
            chunk_config_json={},
            chunk_count=1,
        )
        session.add(succeeded_job)
        session.commit()
        session.refresh(succeeded_job)

        original_status = succeeded_job.status
        original_chunk_count = succeeded_job.chunk_count

        module.run_rechunk_job(
            succeeded_job.id,
            session_factory=_make_session_factory(session),
            upload_storage_root=tmp_path / "uploads",
        )

        session.refresh(succeeded_job)
        assert succeeded_job.status == original_status
        assert succeeded_job.chunk_count == original_chunk_count


# 原始文件缺失时，run_rechunk_job 应将作业标记为 failed 且不抛异常。
def test_run_rechunk_job_fails_when_original_file_missing(tmp_path) -> None:
    module = import_module("app.services.document_chunking")
    models = import_module("app.models.document_chunking")
    with chunking_session() as session:
        user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session,
            tmp_path / "uploads",
        )
        queued_job = models.DocumentChunkJob(
            parsed_document_id=parsed_document.id,
            owner_user_id=user.id,
            status="queued",
            chunker_name="docling_hybrid",
            chunk_config_json={},
        )
        session.add(queued_job)
        session.commit()
        session.refresh(queued_job)

        # 指向不存在的上传存储目录
        module.run_rechunk_job(
            queued_job.id,
            session_factory=_make_session_factory(session),
            upload_storage_root=tmp_path / "nonexistent",
        )

        session.refresh(queued_job)
        assert queued_job.status == "failed"


# 解析器抛错时，run_rechunk_job 应将作业标记为 failed 且不传播异常。
def test_run_rechunk_job_fails_when_parse_throws(tmp_path) -> None:
    module = import_module("app.services.document_chunking")
    models = import_module("app.models.document_chunking")
    with chunking_session() as session:
        user, upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session,
            tmp_path / "uploads",
        )
        queued_job = models.DocumentChunkJob(
            parsed_document_id=parsed_document.id,
            owner_user_id=user.id,
            status="queued",
            chunker_name="docling_hybrid",
            chunk_config_json={},
        )
        session.add(queued_job)
        session.commit()
        session.refresh(queued_job)

        # 不应传播异常
        module.run_rechunk_job(
            queued_job.id,
            session_factory=_make_session_factory(session),
            parser=FakeParser(error=RuntimeError("simulated parse failure")),
            upload_storage_root=tmp_path / "uploads",
        )

        session.refresh(queued_job)
        assert queued_job.status == "failed"


# shutdown 时 run_rechunk_job 应将作业标记为 process_shutdown 且不调用 parser/chunker。
def test_run_rechunk_job_fails_on_shutdown_without_calling_parser_or_chunker(tmp_path) -> None:
    module = import_module("app.services.document_chunking")
    models = import_module("app.models.document_chunking")
    with chunking_session() as session:
        user, upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session,
            tmp_path / "uploads",
        )
        queued_job = models.DocumentChunkJob(
            parsed_document_id=parsed_document.id,
            owner_user_id=user.id,
            status="queued",
            chunker_name="docling_hybrid",
            chunk_config_json={},
        )
        session.add(queued_job)
        session.commit()
        session.refresh(queued_job)

        fake_parser = FakeParser()
        module.run_rechunk_job(
            queued_job.id,
            session_factory=_make_session_factory(session),
            parser=fake_parser,
            upload_storage_root=tmp_path / "uploads",
            shutdown_state=ShutdownState(is_shutting_down=True),
        )

        session.refresh(queued_job)
        assert queued_job.status == "failed"
        assert queued_job.error_code == "process_shutdown"
        assert fake_parser.calls == []


# run_rechunk_job 应使用注入的 session_factory 和 parser，而非默认实现。
def test_run_rechunk_job_uses_injected_dependencies(tmp_path) -> None:
    module = import_module("app.services.document_chunking")
    models = import_module("app.models.document_chunking")
    with chunking_session() as session:
        user, upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session,
            tmp_path / "uploads",
        )
        queued_job = models.DocumentChunkJob(
            parsed_document_id=parsed_document.id,
            owner_user_id=user.id,
            status="queued",
            chunker_name="docling_hybrid",
            chunk_config_json={},
        )
        session.add(queued_job)
        session.commit()
        session.refresh(queued_job)

        fake_parser = FakeParser()
        chunker = FakeChunker()
        service = make_service(module, session, tmp_path, chunker=chunker)

        module.run_rechunk_job(
            queued_job.id,
            session_factory=_make_session_factory(session),
            parser=fake_parser,
            upload_storage_root=tmp_path / "uploads",
            chunking_service=service,
        )

        # 验证注入了 parser 和 chunking_service
        assert len(fake_parser.calls) == 1
        assert chunker.calls != []
