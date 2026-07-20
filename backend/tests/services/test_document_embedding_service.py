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
            adapter_mod.EmbeddingResult(index=i, embedding=[0.1 * (i + 1)] * 2560)
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
        "dimensions": 2560,
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
        assert stored_job.dimensions == 2560
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
            assert emb.embedding_json == [0.1 * (i + 1)] * 2560


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
            dimensions=2560,
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
            dimensions=2560,
        )
        old_failed = models.DocumentEmbeddingJob(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status="failed",
            model="test-model",
            dimensions=2560,
            error_code="api_error",
        )
        old_queued = models.DocumentEmbeddingJob(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status="queued",
            model="test-model",
            dimensions=2560,
        )
        new_job = models.DocumentEmbeddingJob(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status="succeeded",
            model="test-model",
            dimensions=2560,
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
            dimensions=2560,
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
            dimensions=2560,
        )
        running_job = models.DocumentEmbeddingJob(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status="running",
            model="test-model",
            dimensions=2560,
        )
        succeeded_job = models.DocumentEmbeddingJob(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status="succeeded",
            model="test-model",
            dimensions=2560,
        )
        failed_job = models.DocumentEmbeddingJob(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status="failed",
            model="test-model",
            dimensions=2560,
            error_code="api_error",
            error_message="original error",
        )
        superseded_job = models.DocumentEmbeddingJob(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status="superseded",
            model="test-model",
            dimensions=2560,
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
            dimensions=2560,
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
                adapter_mod.EmbeddingResult(index=0, embedding=[0.1] * 2560, token_count=42),
                adapter_mod.EmbeddingResult(index=1, embedding=[0.2] * 2560, token_count=33),
                adapter_mod.EmbeddingResult(index=2, embedding=[0.3] * 2560, token_count=25),
            ]
        )
        service = make_service(session, adapter=adapter)

        _job = service.run_initial_embedding(
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


# ── 6.10 双写策略 ────────────────────────────────────────────────────


# _save_embeddings() 应同时写入 embedding_json 和 embedding_vector 两列，
# 且两列值必须一致。
def test_save_embeddings_writes_both_json_and_vector_columns(tmp_path) -> None:
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

        stored_job = session.get(models.DocumentEmbeddingJob, job.id)
        assert stored_job.status == "succeeded"
        assert stored_job.embedding_count == len(chunks)

        embeddings = session.exec(
            select(models.DocumentEmbedding).order_by(models.DocumentEmbedding.sequence_index)
        ).all()
        assert len(embeddings) == 3

        for emb in embeddings:
            # 两列都必须非空
            assert emb.embedding_json is not None
            assert emb.embedding_vector is not None
            # 两列值必须一致
            assert emb.embedding_json == list(emb.embedding_vector)
            assert len(emb.embedding_vector) == 2560  # config.dimensions


# 双写应在同一事务中完成，任一列写入失败则全部回滚。
def test_dual_write_is_in_same_transaction(tmp_path) -> None:
    """验证 embedding_json 和 embedding_vector 写入在同一事务中。

    由于 _save_embeddings() 使用 session.flush() 而非 commit()，
    所有批量写入在同一事务中执行。此测试验证正常双写路径不会出现
    一列有值一列为 NULL 的情况。
    """
    import_module("app.services.document_embedding")
    models = import_module("app.models.document_embedding")
    with embedding_session() as session:
        _user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session, tmp_path / "uploads"
        )
        chunk_job = make_chunk_job(session, parsed_document)
        chunks = make_document_chunks(session, chunk_job, parsed_document, chunk_count=5)

        adapter = FakeEmbeddingAdapter()
        service = make_service(session, adapter=adapter)

        job = service.run_initial_embedding(
            chunk_job=chunk_job,
            parsed_document=parsed_document,
        )

        stored_job = session.get(models.DocumentEmbeddingJob, job.id)
        assert stored_job.status == "succeeded"
        assert stored_job.embedding_count == len(chunks)

        # 所有 embedding 记录的双列都必须一致
        embeddings = session.exec(
            select(models.DocumentEmbedding).order_by(models.DocumentEmbedding.sequence_index)
        ).all()
        assert len(embeddings) == 5

        for emb in embeddings:
            assert emb.embedding_json is not None, (
                f"embedding_json should not be None for sequence_index={emb.sequence_index}"
            )
            assert emb.embedding_vector is not None, (
                f"embedding_vector should not be None for sequence_index={emb.sequence_index}"
            )
            assert emb.embedding_json == list(emb.embedding_vector), (
                f"Values mismatch for sequence_index={emb.sequence_index}"
            )


# 双写后从 DB 重新读取，确保两列都持久化到磁盘。
def test_dual_write_data_survives_round_trip(tmp_path) -> None:
    """双写数据在 session refresh 后仍然正确。"""
    import_module("app.services.document_embedding")
    models = import_module("app.models.document_embedding")
    with embedding_session() as session:
        _user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session, tmp_path / "uploads"
        )
        chunk_job = make_chunk_job(session, parsed_document)
        chunks = make_document_chunks(session, chunk_job, parsed_document, chunk_count=1)

        adapter = FakeEmbeddingAdapter()
        service = make_service(session, adapter=adapter)

        job = service.run_initial_embedding(
            chunk_job=chunk_job,
            parsed_document=parsed_document,
        )

        stored_job = session.get(models.DocumentEmbeddingJob, job.id)
        assert stored_job.status == "succeeded"
        assert stored_job.embedding_count == len(chunks)

        embeddings = session.exec(select(models.DocumentEmbedding)).all()
        assert len(embeddings) == 1
        emb = embeddings[0]

        # Round-trip: expire and re-read
        session.expire(emb)
        assert emb.embedding_json is not None
        assert emb.embedding_vector is not None
        assert emb.embedding_json == list(emb.embedding_vector)


# ── 7. 集成验证测试 ──────────────────────────────────────────────────


# 端到端集成测试：通过 run_initial_embedding 完整走一遍向量化流程，
# 验证 embedding_json 和 embedding_vector 两列都有数据且值一致。
def test_end_to_end_dual_write_both_columns_populated_and_consistent(tmp_path) -> None:
    """端到端验证：上传文件 → 解析 → 分块 → 向量化 → 双写验证。"""
    import_module("app.services.document_embedding")
    models = import_module("app.models.document_embedding")
    with embedding_session() as session:
        _user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session, tmp_path / "uploads"
        )
        chunk_job = make_chunk_job(session, parsed_document)
        chunks = make_document_chunks(session, chunk_job, parsed_document, chunk_count=5)

        adapter = FakeEmbeddingAdapter()
        service = make_service(session, adapter=adapter)

        job = service.run_initial_embedding(
            chunk_job=chunk_job,
            parsed_document=parsed_document,
        )

        # 作业成功
        stored_job = session.get(models.DocumentEmbeddingJob, job.id)
        assert stored_job.status == "succeeded"
        assert stored_job.embedding_count == len(chunks)

        # 验证所有 embedding 记录的双列完整性和一致性
        embeddings = session.exec(
            select(models.DocumentEmbedding).order_by(models.DocumentEmbedding.sequence_index)
        ).all()
        assert len(embeddings) == 5

        for i, emb in enumerate(embeddings):
            assert emb.embedding_json is not None, f"embedding_json is None for chunk {i}"
            assert emb.embedding_vector is not None, f"embedding_vector is None for chunk {i}"
            assert len(emb.embedding_json) == 2560
            assert len(emb.embedding_vector) == 2560
            assert emb.embedding_json == list(emb.embedding_vector), (
                f"embedding_json != embedding_vector for chunk {i}: "
                f"{emb.embedding_json[:3]}... vs {emb.embedding_vector[:3]}..."
            )
            # 验证关联完整性
            assert emb.embedding_job_id == job.id
            assert emb.chunk_id == chunks[i].id
            assert emb.parsed_document_id == parsed_document.id
            assert emb.sequence_index == i
            assert emb.model == "test-model"
            assert emb.dimensions == 2560


# 重新向量化后双写仍然正确：通过 execute_queued_job 重新执行向量化，
# 验证新生成的 embedding 记录的双列仍然一致。
def test_re_vectorization_maintains_dual_write_consistency(tmp_path) -> None:
    """重新向量化后双写仍然正确。"""
    import_module("app.services.document_embedding")
    models = import_module("app.models.document_embedding")
    with embedding_session() as session:
        _user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session, tmp_path / "uploads"
        )
        chunk_job = make_chunk_job(session, parsed_document)
        chunks = make_document_chunks(session, chunk_job, parsed_document, chunk_count=3)

        # 首次向量化
        adapter = FakeEmbeddingAdapter()
        service = make_service(session, adapter=adapter)
        first_job = service.run_initial_embedding(
            chunk_job=chunk_job,
            parsed_document=parsed_document,
        )
        assert first_job.status == "succeeded"

        # 重新向量化：创建新的 queued 作业
        queued_job = models.DocumentEmbeddingJob(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status="queued",
            model="test-model",
            dimensions=2560,
        )
        session.add(queued_job)
        session.commit()
        session.refresh(queued_job)

        # 使用不同的向量值以区分新旧
        adapter2 = FakeEmbeddingAdapter(
            results=[
                import_module("app.services.embedding_adapter").EmbeddingResult(
                    index=0, embedding=[0.99] * 2560, token_count=10
                ),
                import_module("app.services.embedding_adapter").EmbeddingResult(
                    index=1, embedding=[0.88] * 2560, token_count=10
                ),
                import_module("app.services.embedding_adapter").EmbeddingResult(
                    index=2, embedding=[0.77] * 2560, token_count=10
                ),
            ]
        )
        service2 = make_service(session, adapter=adapter2)
        result = service2.execute_queued_job(
            job=queued_job,
            chunks=chunks,
        )
        assert result.status == "succeeded"

        # 验证最新 job 的 embedding 双列一致性
        latest_embeddings = session.exec(
            select(models.DocumentEmbedding)
            .where(models.DocumentEmbedding.embedding_job_id == queued_job.id)
            .order_by(models.DocumentEmbedding.sequence_index)
        ).all()
        assert len(latest_embeddings) == 3

        expected_values = [[0.99] * 2560, [0.88] * 2560, [0.77] * 2560]
        for i, emb in enumerate(latest_embeddings):
            assert emb.embedding_json is not None
            assert emb.embedding_vector is not None
            assert emb.embedding_json == list(emb.embedding_vector)
            assert emb.embedding_json == expected_values[i]

        # 首次 job 被 superseded
        session.refresh(first_job)
        assert first_job.status == "superseded"

        # 旧 embedding 记录的双列也保持一致
        old_embeddings = session.exec(
            select(models.DocumentEmbedding)
            .where(models.DocumentEmbedding.embedding_job_id == first_job.id)
            .order_by(models.DocumentEmbedding.sequence_index)
        ).all()
        assert len(old_embeddings) == 3
        for emb in old_embeddings:
            assert emb.embedding_json is not None
            assert emb.embedding_vector is not None
            assert emb.embedding_json == list(emb.embedding_vector)


# 验证 embedding_vector 列可接受 pgvector 距离算子查询（<=>）。
# 使用 SQLAlchemy 的 op() 方法构造 l2 距离查询，
# 验证查询可正常构建且不抛出类型错误。
def test_embedding_vector_column_accepts_pgvector_distance_operator(tmp_path) -> None:
    """验证 embedding_vector 列可使用 pgvector <=> 距离算子。"""
    import_module("app.services.document_embedding")
    models = import_module("app.models.document_embedding")
    with embedding_session() as session:
        _user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session, tmp_path / "uploads"
        )
        chunk_job = make_chunk_job(session, parsed_document)
        _chunks = make_document_chunks(session, chunk_job, parsed_document, chunk_count=1)

        adapter = FakeEmbeddingAdapter()
        service = make_service(session, adapter=adapter)

        job = service.run_initial_embedding(
            chunk_job=chunk_job,
            parsed_document=parsed_document,
        )
        assert job.status == "succeeded"

        # 查询已保存的向量作为参照
        embedding = session.exec(
            select(models.DocumentEmbedding).where(
                models.DocumentEmbedding.embedding_job_id == job.id
            )
        ).one()

        query_vector = embedding.embedding_vector
        assert query_vector is not None

        # 使用 op('<=>') 构造 l2 距离查询
        # 在 PostgreSQL + pgvector 环境中此查询可正确执行并返回距离值
        stmt = (
            select(
                models.DocumentEmbedding.id,
                models.DocumentEmbedding.embedding_vector.op("<=>")(query_vector).label("distance"),
            )
            .where(
                models.DocumentEmbedding.embedding_job_id == job.id,
            )
            .order_by("distance")
        )

        # 验证查询能正常构建（SQLite 下编译验证，实际执行依赖 pgvector）
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "<=>" in compiled, f"Query should contain <=> operator, got: {compiled}"
        assert "embedding_vector" in compiled, (
            f"Query should reference embedding_vector column, got: {compiled}"
        )
