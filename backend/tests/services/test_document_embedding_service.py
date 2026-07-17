# 本文件验证 DocumentEmbeddingService 的核心业务语义。
# 覆盖初次向量化、文本选择策略、状态转换、作业取代、异常处理和 shutdown 协作。

from collections.abc import Generator
from contextlib import contextmanager
from importlib import import_module

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from tests.document_chunking_helpers import make_parsed_document_with_segment


@contextmanager
def embedding_session() -> Generator[Session]:
    """创建包含向量化模型的内存 SQLite session。"""
    __import__("app.models.uploaded_file")
    __import__("app.models.document_parsing")
    __import__("app.models.document_chunking")
    __import__("app.models.document_embedding")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        yield session


class FakeEmbeddingAdapter:
    """可控的 fake embedding 适配器，返回固定向量或抛出异常。"""

    def __init__(self, results=None, error=None):
        self.results = results
        self.error = error
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(texts)
        if self.error is not None:
            raise self.error
        if self.results is not None:
            return self.results
        adapter_mod = import_module("app.services.embedding_adapter")
        return [
            adapter_mod.EmbeddingResult(index=i, embedding=[0.1 * (i + 1)] * 128)
            for i in range(len(texts))
        ]


class ShutdownState:
    def __init__(self, *, is_shutting_down: bool = True) -> None:
        self.is_shutting_down = is_shutting_down


def make_config(**overrides):
    """创建测试用 EmbeddingConfig。"""
    config_mod = import_module("app.services.embedding_config")
    defaults = {
        "api_base_url": "https://test.example.com/v1",
        "api_key": "sk-test",
        "model": "test-model",
        "dimensions": 128,
        "encoding_format": "float",
        "batch_size": 10,
        "max_retries": 3,
        "request_timeout": 30.0,
    }
    defaults.update(overrides)
    return config_mod.EmbeddingConfig(**defaults)


def make_service(session, adapter=None, config=None, shutdown_state=None):
    module = import_module("app.services.document_embedding")
    return module.DocumentEmbeddingService(
        session=session,
        adapter=adapter or FakeEmbeddingAdapter(),
        config=config or make_config(),
        shutdown_state=shutdown_state,
    )


def make_chunk_job(session, parsed_document, *, status: str = "succeeded"):
    """创建一个测试用 DocumentChunkJob。"""
    models = import_module("app.models.document_chunking")
    job = models.DocumentChunkJob(
        parsed_document_id=parsed_document.id,
        owner_user_id=parsed_document.owner_user_id,
        status=status,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def make_document_chunks(session, chunk_job, parsed_document, chunk_count=3):
    """创建与 chunk_job 关联的测试用 DocumentChunks。"""
    models = import_module("app.models.document_chunking")
    chunks = []
    for i in range(chunk_count):
        chunk = models.DocumentChunk(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            sequence_index=i,
            text=f"Text chunk {i}",
            contextualized_text=f"Contextualized chunk {i}",
            token_count=10,
        )
        session.add(chunk)
        chunks.append(chunk)
    session.commit()
    for chunk in chunks:
        session.refresh(chunk)
    return chunks


# ── 6.1 run_initial_embedding ────────────────────────────────────────


# 初次向量化应创建作业、调用适配器并持久化向量结果。
# 测试确认作业状态为 succeeded，适配器收到正确的文本，向量按 sequence_index 保存。
def test_run_initial_embedding_creates_job_and_succeeds(tmp_path) -> None:
    import_module("app.services.document_embedding")
    models = import_module("app.models.document_embedding")
    with embedding_session() as session:
        _user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session, tmp_path / "uploads"
        )
        chunk_job = make_chunk_job(session, parsed_document)
        chunks = make_document_chunks(session, chunk_job, parsed_document)

        adapter = FakeEmbeddingAdapter()
        service = make_service(session, adapter=adapter)

        job = service.run_initial_embedding(
            chunk_job=chunk_job,
            parsed_document=parsed_document,
        )

        # 作业应成功
        stored_job = session.get(models.DocumentEmbeddingJob, job.id)
        assert stored_job.status == "succeeded"
        assert stored_job.embedding_count == 3
        assert stored_job.model == "test-model"
        assert stored_job.dimensions == 128
        assert stored_job.config_json == make_config().snapshot()
        # 适配器应被调用一次，传入 3 个 contextualized_text
        assert len(adapter.calls) == 1
        assert adapter.calls[0] == [
            chunks[0].contextualized_text,
            chunks[1].contextualized_text,
            chunks[2].contextualized_text,
        ]
        # 向量结果应持久化，按 sequence_index 关联
        embeddings = session.exec(
            select(models.DocumentEmbedding).order_by(models.DocumentEmbedding.sequence_index)
        ).all()
        assert len(embeddings) == 3
        for i, emb in enumerate(embeddings):
            assert emb.embedding_job_id == job.id
            assert emb.chunk_id == chunks[i].id
            assert emb.sequence_index == i
            assert emb.embedding_json == [0.1 * (i + 1)] * 128


# ── 6.2 文本选择策略 ────────────────────────────────────────────────


# 向量化文本应优先使用 contextualized_text，为空时回退到 text，
# 两者都为空时使用空字符串。
def test_text_selection_prefers_contextualized_text_over_text(tmp_path) -> None:
    import_module("app.services.document_embedding")
    models = import_module("app.models.document_chunking")
    with embedding_session() as session:
        _user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session, tmp_path / "uploads"
        )
        chunk_job = make_chunk_job(session, parsed_document)
        # 创建三个 chunks 覆盖三种文本选择场景
        chunks_data = [
            # (contextualized_text, text, expected)
            ("Context A", "Text A", "Context A"),
            (None, "Text B", "Text B"),
            (None, None, ""),
        ]
        chunks = []
        for i, (ctx_text, plain_text, _expected) in enumerate(chunks_data):
            chunk = models.DocumentChunk(
                chunk_job_id=chunk_job.id,
                parsed_document_id=parsed_document.id,
                owner_user_id=parsed_document.owner_user_id,
                sequence_index=i,
                text=plain_text,
                contextualized_text=ctx_text,
            )
            session.add(chunk)
            chunks.append(chunk)
        session.commit()
        for chunk in chunks:
            session.refresh(chunk)

        adapter = FakeEmbeddingAdapter()
        service = make_service(session, adapter=adapter)

        service.run_initial_embedding(
            chunk_job=chunk_job,
            parsed_document=parsed_document,
        )

        texts_sent = adapter.calls[0]
        assert texts_sent[0] == "Context A"
        assert texts_sent[1] == "Text B"
        assert texts_sent[2] == ""


# ── 6.3 _run_job 状态转换 ────────────────────────────────────────────


# _run_job 应将作业状态从 queued 转换为 succeeded，
# embedding_count 应与 chunks 数量一致。
def test_run_job_transitions_status_to_succeeded_and_sets_embedding_count(tmp_path) -> None:
    import_module("app.services.document_embedding")
    models = import_module("app.models.document_embedding")
    with embedding_session() as session:
        _user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session, tmp_path / "uploads"
        )
        chunk_job = make_chunk_job(session, parsed_document)
        chunks = make_document_chunks(session, chunk_job, parsed_document, chunk_count=5)

        # 创建 queued 状态的作业
        queued_job = models.DocumentEmbeddingJob(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status="queued",
            model="test-model",
            dimensions=128,
        )
        session.add(queued_job)
        session.commit()
        session.refresh(queued_job)

        service = make_service(session)

        result = service._run_job(
            job=queued_job,
            chunks=chunks,
            supersede_previous=False,
        )

        assert result.status == "succeeded"
        assert result.embedding_count == 5
        assert result.started_at is not None
        assert result.finished_at is not None
        assert result.attempt_count >= 1
        # 向量结果数量应与 chunks 一致
        embeddings = session.exec(select(models.DocumentEmbedding)).all()
        assert len(embeddings) == 5


# ── 6.4 _supersede_previous_jobs ─────────────────────────────────────


# _supersede_previous_jobs 应将同一 chunk_job_id 下的旧 succeeded 作业
# 标记为 superseded，其他状态保持不变。
def test_supersede_previous_jobs_marks_only_old_succeeded_as_superseded(tmp_path) -> None:
    import_module("app.services.document_embedding")
    models = import_module("app.models.document_embedding")
    with embedding_session() as session:
        _user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session, tmp_path / "uploads"
        )
        chunk_job = make_chunk_job(session, parsed_document)

        # 创建不同状态的旧作业
        old_succeeded = models.DocumentEmbeddingJob(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status="succeeded",
            model="test-model",
            dimensions=128,
        )
        old_failed = models.DocumentEmbeddingJob(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status="failed",
            model="test-model",
            dimensions=128,
            error_code="api_error",
        )
        old_queued = models.DocumentEmbeddingJob(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status="queued",
            model="test-model",
            dimensions=128,
        )
        new_job = models.DocumentEmbeddingJob(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status="succeeded",
            model="test-model",
            dimensions=128,
        )
        for job in (old_succeeded, old_failed, old_queued, new_job):
            session.add(job)
        session.commit()

        service = make_service(session)

        service._supersede_previous_jobs(
            chunk_job_id=chunk_job.id,
            keep_job=new_job,
        )
        # _supersede_previous_jobs 不自行提交 —— 在生产代码中由 _run_job 的
        # finally 块统一提交。测试中需要显式提交以验证数据库状态。
        session.commit()

        session.refresh(old_succeeded)
        session.refresh(old_failed)
        session.refresh(old_queued)
        session.refresh(new_job)

        # 只有旧 succeeded 被标记为 superseded
        assert old_succeeded.status == "superseded"
        # 其他状态保持不变
        assert old_failed.status == "failed"
        assert old_queued.status == "queued"
        # 新作业不受影响
        assert new_job.status == "succeeded"


# ── 6.5 execute_queued_job ───────────────────────────────────────────


# execute_queued_job 不创建新作业，直接使用传入的 job 参数执行向量化。
def test_execute_queued_job_does_not_create_new_job(tmp_path) -> None:
    import_module("app.services.document_embedding")
    models = import_module("app.models.document_embedding")
    with embedding_session() as session:
        _user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session, tmp_path / "uploads"
        )
        chunk_job = make_chunk_job(session, parsed_document)
        chunks = make_document_chunks(session, chunk_job, parsed_document)

        queued_job = models.DocumentEmbeddingJob(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status="queued",
            model="test-model",
            dimensions=128,
        )
        session.add(queued_job)
        session.commit()
        session.refresh(queued_job)

        job_count_before = len(session.exec(select(models.DocumentEmbeddingJob)).all())
        service = make_service(session)

        result = service.execute_queued_job(
            job=queued_job,
            chunks=chunks,
        )

        job_count_after = len(session.exec(select(models.DocumentEmbeddingJob)).all())
        # 返回同一个作业
        assert result.id == queued_job.id
        assert result.status == "succeeded"
        # 作业数量不变 — 没有创建新作业
        assert job_count_after == job_count_before


# ── 6.6 异常处理 ────────────────────────────────────────────────────


# 适配器抛出 EmbeddingAPIError 时作业标记为 failed，
# error_code 为 api_error，不创建向量结果（不滚回已存在数据）。
def test_adapter_error_marks_job_failed_with_api_error_code(tmp_path) -> None:
    import_module("app.services.document_embedding")
    adapter_module = import_module("app.services.embedding_adapter")
    models = import_module("app.models.document_embedding")
    with embedding_session() as session:
        _user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session, tmp_path / "uploads"
        )
        chunk_job = make_chunk_job(session, parsed_document)
        make_document_chunks(session, chunk_job, parsed_document)

        adapter = FakeEmbeddingAdapter(
            error=adapter_module.EmbeddingAPIError("API timeout", status_code=500)
        )
        service = make_service(session, adapter=adapter)

        job = service.run_initial_embedding(
            chunk_job=chunk_job,
            parsed_document=parsed_document,
        )

        stored_job = session.get(models.DocumentEmbeddingJob, job.id)
        assert stored_job.status == "failed"
        assert stored_job.error_code == "api_error"
        assert "API timeout" in stored_job.error_message
        assert stored_job.finished_at is not None
        # 不应创建向量结果
        embeddings = session.exec(select(models.DocumentEmbedding)).all()
        assert len(embeddings) == 0


# EmbeddingInvalidResponseError 应将作业标记为 failed，
# error_code 为 invalid_response。
def test_invalid_response_error_marks_job_failed_with_invalid_response_code(tmp_path) -> None:
    import_module("app.services.document_embedding")
    adapter_module = import_module("app.services.embedding_adapter")
    models = import_module("app.models.document_embedding")
    with embedding_session() as session:
        _user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session, tmp_path / "uploads"
        )
        chunk_job = make_chunk_job(session, parsed_document)
        make_document_chunks(session, chunk_job, parsed_document)

        adapter = FakeEmbeddingAdapter(
            error=adapter_module.EmbeddingInvalidResponseError(
                "Expected 3 embeddings but received 2"
            )
        )
        service = make_service(session, adapter=adapter)

        job = service.run_initial_embedding(
            chunk_job=chunk_job,
            parsed_document=parsed_document,
        )

        stored_job = session.get(models.DocumentEmbeddingJob, job.id)
        assert stored_job.status == "failed"
        assert stored_job.error_code == "invalid_response"
        assert "Expected 3" in stored_job.error_message


# ── 6.7 shutdown 收尾 ───────────────────────────────────────────────


# shutdown 收尾应将 queued 和 running 向量化作业标记为 process_shutdown，
# 不覆盖已完成作业（succeeded / failed / superseded）。
def test_mark_incomplete_embedding_jobs_failed_for_shutdown(tmp_path) -> None:
    module = import_module("app.services.document_embedding")
    models = import_module("app.models.document_embedding")
    with embedding_session() as session:
        _user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session, tmp_path / "uploads"
        )
        chunk_job = make_chunk_job(session, parsed_document)

        # 创建五种状态的作业
        queued_job = models.DocumentEmbeddingJob(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status="queued",
            model="test-model",
            dimensions=128,
        )
        running_job = models.DocumentEmbeddingJob(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status="running",
            model="test-model",
            dimensions=128,
        )
        succeeded_job = models.DocumentEmbeddingJob(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status="succeeded",
            model="test-model",
            dimensions=128,
        )
        failed_job = models.DocumentEmbeddingJob(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status="failed",
            model="test-model",
            dimensions=128,
            error_code="api_error",
            error_message="original error",
        )
        superseded_job = models.DocumentEmbeddingJob(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status="superseded",
            model="test-model",
            dimensions=128,
        )
        for j in (queued_job, running_job, succeeded_job, failed_job, superseded_job):
            session.add(j)
        session.commit()

        count = module.mark_incomplete_embedding_jobs_failed_for_shutdown(
            session=session,
            reason="signal",
        )

        for j in (queued_job, running_job, succeeded_job, failed_job, superseded_job):
            session.refresh(j)

        # 只标记了 2 个未完成作业
        assert count == 2
        for j in (queued_job, running_job):
            assert j.status == "failed"
            assert j.error_code == "process_shutdown"
            assert "shutdown" in j.error_message.lower()
            assert j.finished_at is not None
        # 已完成的不被修改
        assert succeeded_job.status == "succeeded"
        assert succeeded_job.error_code is None
        assert failed_job.status == "failed"
        assert failed_job.error_code == "api_error"
        assert failed_job.error_message == "original error"
        assert superseded_job.status == "superseded"


# ── 6.8 execute_queued_job shutdown 快速失败 ──────────────────────────


# execute_queued_job 在 shutdown 时应快速失败，标记 process_shutdown 且不调用适配器。
def test_execute_queued_job_fast_fails_on_shutdown_without_calling_adapter(tmp_path) -> None:
    import_module("app.services.document_embedding")
    models = import_module("app.models.document_embedding")
    with embedding_session() as session:
        _user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session, tmp_path / "uploads"
        )
        chunk_job = make_chunk_job(session, parsed_document)
        chunks = make_document_chunks(session, chunk_job, parsed_document)

        queued_job = models.DocumentEmbeddingJob(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status="queued",
            model="test-model",
            dimensions=128,
        )
        session.add(queued_job)
        session.commit()
        session.refresh(queued_job)

        adapter = FakeEmbeddingAdapter()
        service = make_service(
            session,
            adapter=adapter,
            shutdown_state=ShutdownState(is_shutting_down=True),
        )

        result = service.execute_queued_job(
            job=queued_job,
            chunks=chunks,
        )

        stored_job = session.get(models.DocumentEmbeddingJob, result.id)
        assert stored_job.status == "failed"
        assert stored_job.error_code == "process_shutdown"
        assert stored_job.finished_at is not None
        # 适配器不应被调用
        assert adapter.calls == []


# ── 6.9 token_count 传递 ──────────────────────────────────────────────


# 适配器返回的 EmbeddingResult.token_count 应被持久化到 DocumentEmbedding。
def test_token_count_persisted_from_adapter_result(tmp_path) -> None:
    import_module("app.services.document_embedding")
    adapter_mod = import_module("app.services.embedding_adapter")
    models = import_module("app.models.document_embedding")
    with embedding_session() as session:
        _user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session, tmp_path / "uploads"
        )
        chunk_job = make_chunk_job(session, parsed_document)
        make_document_chunks(session, chunk_job, parsed_document, chunk_count=3)

        # 适配器返回带 token_count 的结果
        adapter = FakeEmbeddingAdapter(
            results=[
                adapter_mod.EmbeddingResult(index=0, embedding=[0.1] * 128, token_count=42),
                adapter_mod.EmbeddingResult(index=1, embedding=[0.2] * 128, token_count=33),
                adapter_mod.EmbeddingResult(index=2, embedding=[0.3] * 128, token_count=25),
            ]
        )
        service = make_service(session, adapter=adapter)

        job = service.run_initial_embedding(
            chunk_job=chunk_job,
            parsed_document=parsed_document,
        )

        # 验证 token_count 已持久化
        embeddings = session.exec(
            select(models.DocumentEmbedding).order_by(models.DocumentEmbedding.sequence_index)
        ).all()
        assert len(embeddings) == 3
        assert embeddings[0].token_count == 42
        assert embeddings[1].token_count == 33
        assert embeddings[2].token_count == 25
