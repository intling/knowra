"""本文件验证文档向量化模块的端到端集成行为。
覆盖完整自动链路（解析 → 分块 → 向量化）、向量化禁用跳过、
自动向量化失败不回滚、graceful shutdown 收尾和重新向量化端到端流程。
"""

from collections.abc import Generator
from contextlib import contextmanager, suppress
from importlib import import_module

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from tests.document_chunking_helpers import (
    make_minimal_docling_document,
    make_parsed_document_with_segment,
)
from tests.document_parsing_helpers import (
    ParsedPayloadFactory,
    SessionFactory,
    make_uploaded_file,
    make_user,
)


@pytest.fixture
def session() -> Generator[Session]:
    """提供包含所有文档管线模型的内存 SQLite session。"""
    import_module("app.models.uploaded_file")
    with suppress(ModuleNotFoundError):
        import_module("app.models.document_parsing")
    with suppress(ModuleNotFoundError):
        import_module("app.models.document_chunking")
    with suppress(ModuleNotFoundError):
        import_module("app.models.document_embedding")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as test_session:
        yield test_session


# ── Fake 组件（供集成测试注入）──────────────────────────────────────────


class ParserReturningTransientResult:
    """返回有效解析结果 + 内存 DoclingDocument 的 fake parser。"""

    def __init__(self, transient_docling_document=None):
        self.payload = ParsedPayloadFactory().make()
        self.transient = transient_docling_document or make_minimal_docling_document()

    def parse(self, *_args, **_kwargs):
        parser_mod = import_module("app.services.document_parser")
        return parser_mod.ParsedDocumentResult(
            persistent_payload=self.payload,
            transient_docling_document=self.transient,
        )


class IntegrationChunkingService:
    """在 DB 中创建真实的 DocumentChunkJob 和 DocumentChunks。

    这样真实的 DocumentEmbeddingService 才能找到 chunks 来生成向量。
    """

    def __init__(self, session, *, error=None):
        self.session = session
        self.error = error

    def run_initial_chunking(self, *, parsed_document, transient_docling_document):
        if self.error is not None:
            raise self.error

        chunk_mod = import_module("app.models.document_chunking")
        chunk_job = chunk_mod.DocumentChunkJob(
            parsed_document_id=parsed_document.id,
            owner_user_id=parsed_document.owner_user_id,
            status="succeeded",
            chunker_name="docling_hybrid",
            chunker_version="test",
            chunk_config_json={},
            chunk_count=3,
        )
        self.session.add(chunk_job)
        self.session.commit()
        self.session.refresh(chunk_job)

        for i in range(3):
            self.session.add(
                chunk_mod.DocumentChunk(
                    chunk_job_id=chunk_job.id,
                    parsed_document_id=parsed_document.id,
                    owner_user_id=parsed_document.owner_user_id,
                    sequence_index=i,
                    text=f"Chunk text {i}",
                    contextualized_text=f"Contextualized chunk {i}",
                    token_count=10,
                    heading_path=["Test"],
                    page_numbers=[1],
                    chunk_type="text",
                    source_segment_indices=[0],
                )
            )
        self.session.commit()
        return chunk_job


class IntegrationEmbeddingAdapter:
    """可控的 fake embedding 适配器 —— 返回固定向量或抛出异常。"""

    def __init__(self, *, error=None, dimensions=2560):
        self.error = error
        self.dimensions = dimensions
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        if self.error is not None:
            raise self.error
        adapter_mod = import_module("app.services.embedding_adapter")
        return [
            adapter_mod.EmbeddingResult(index=i, embedding=[0.1 * (i + 1)] * self.dimensions)
            for i in range(len(texts))
        ]


def make_embedding_service(session, adapter, *, shutdown_state=None):
    """创建使用 fake adapter 的真实 DocumentEmbeddingService。"""
    service_mod = import_module("app.services.document_embedding")
    config_mod = import_module("app.services.embedding_config")
    config = config_mod.EmbeddingConfig(
        api_base_url="https://test.example.com/v1",
        api_key="sk-test",
        model="test-model",
        dimensions=2560,
        encoding_format="float",
        batch_size=10,
        max_retries=3,
        request_timeout=30.0,
    )
    return service_mod.DocumentEmbeddingService(
        session=session,
        adapter=adapter,
        config=config,
        shutdown_state=shutdown_state,
    )


def make_parse_job(session, tmp_path):
    """种下 queued 解析作业及其上传文件，返回 models 模块、job、user。"""
    models = import_module("app.models.document_parsing")
    user = make_user(session)
    upload = make_uploaded_file(session, tmp_path / "uploads", user)
    job = models.DocumentParseJob(
        uploaded_file_id=upload.id,
        owner_user_id=user.id,
        status="queued",
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return models, job, user


# ═══════════════════════════════════════════════════════════════════════════
# 10.1  完整自动链路（解析 → 分块 → 向量化）
# ═══════════════════════════════════════════════════════════════════════════


def test_full_auto_pipeline_parse_chunk_embed_succeeds(session, tmp_path):
    """完整自动链路应将解析、分块和向量化全部执行成功。

    mock 适配器返回固定向量，验证：解析成功 → 分块成功 → 向量化作业 succeeded
    → 向量结果按 sequence_index 持久化。
    """
    dispatcher = import_module("app.services.document_parse_dispatcher")
    models, job, _user = make_parse_job(session, tmp_path)
    emb_models = import_module("app.models.document_embedding")

    fake_adapter = IntegrationEmbeddingAdapter(dimensions=2560)
    embedding_service = make_embedding_service(session, fake_adapter)
    chunking_service = IntegrationChunkingService(session)

    dispatcher.run_parse_job(
        job.id,
        session_factory=SessionFactory(session),
        parser=ParserReturningTransientResult(),
        upload_storage_root=tmp_path / "uploads",
        artifact_storage_root=tmp_path / "parsed",
        document_chunking_enabled=True,
        chunking_service=chunking_service,
        document_embedding_enabled=True,
        embedding_service=embedding_service,
    )

    # 解析作业应成功
    stored_parse = session.get(models.DocumentParseJob, job.id)
    assert stored_parse.status == "succeeded"
    # 解析结果应持久化
    parsed_docs = session.exec(select(models.ParsedDocument)).all()
    assert len(parsed_docs) == 1

    # 向量化作业应成功
    emb_jobs = session.exec(select(emb_models.DocumentEmbeddingJob)).all()
    assert len(emb_jobs) == 1
    emb_job = emb_jobs[0]
    assert emb_job.status == "succeeded"
    assert emb_job.embedding_count == 3
    assert emb_job.model == "test-model"
    assert emb_job.dimensions == 2560

    # 适配器应收到 3 个 contextualized_text
    assert len(fake_adapter.calls) == 1
    assert fake_adapter.calls[0] == [
        "Contextualized chunk 0",
        "Contextualized chunk 1",
        "Contextualized chunk 2",
    ]

    # 向量结果应按 sequence_index 顺序持久化
    embeddings = session.exec(
        select(emb_models.DocumentEmbedding).order_by(emb_models.DocumentEmbedding.sequence_index)
    ).all()
    assert len(embeddings) == 3
    for i, emb in enumerate(embeddings):
        assert emb.sequence_index == i
        assert emb.dimensions == 2560
        assert emb.embedding_json == [0.1 * (i + 1)] * 2560


# ═══════════════════════════════════════════════════════════════════════════
# 10.2  向量化功能禁用时链路跳过
# ═══════════════════════════════════════════════════════════════════════════


def test_embedding_disabled_skips_embed_parse_and_chunk_still_succeed(session, tmp_path):
    """向量化禁用时解析和分块应成功，不创建向量化作业。"""
    dispatcher = import_module("app.services.document_parse_dispatcher")
    models, job, _user = make_parse_job(session, tmp_path)
    emb_models = import_module("app.models.document_embedding")
    chunk_models = import_module("app.models.document_chunking")

    chunking_service = IntegrationChunkingService(session)

    dispatcher.run_parse_job(
        job.id,
        session_factory=SessionFactory(session),
        parser=ParserReturningTransientResult(),
        upload_storage_root=tmp_path / "uploads",
        artifact_storage_root=tmp_path / "parsed",
        document_chunking_enabled=True,
        chunking_service=chunking_service,
        document_embedding_enabled=False,
    )

    # 解析作业应成功
    stored_parse = session.get(models.DocumentParseJob, job.id)
    assert stored_parse.status == "succeeded"

    # 分块作业应成功
    chunk_jobs = session.exec(select(chunk_models.DocumentChunkJob)).all()
    assert len(chunk_jobs) == 1
    assert chunk_jobs[0].status == "succeeded"

    # 不应创建向量化作业
    emb_jobs = session.exec(select(emb_models.DocumentEmbeddingJob)).all()
    assert emb_jobs == []

    # 不应创建向量结果
    embeddings = session.exec(select(emb_models.DocumentEmbedding)).all()
    assert embeddings == []


# ═══════════════════════════════════════════════════════════════════════════
# 10.3  自动向量化失败不回滚解析/分块
# ═══════════════════════════════════════════════════════════════════════════


def test_embedding_failure_keeps_parse_and_chunk_succeeded(session, tmp_path):
    """自动向量化失败时解析和分块保持 succeeded，向量化作业为 failed。"""
    dispatcher = import_module("app.services.document_parse_dispatcher")
    models, job, _user = make_parse_job(session, tmp_path)
    emb_models = import_module("app.models.document_embedding")
    chunk_models = import_module("app.models.document_chunking")
    adapter_mod = import_module("app.services.embedding_adapter")

    failing_adapter = IntegrationEmbeddingAdapter(
        error=adapter_mod.EmbeddingAPIError("API timeout", status_code=500)
    )
    embedding_service = make_embedding_service(session, failing_adapter)
    chunking_service = IntegrationChunkingService(session)

    dispatcher.run_parse_job(
        job.id,
        session_factory=SessionFactory(session),
        parser=ParserReturningTransientResult(),
        upload_storage_root=tmp_path / "uploads",
        artifact_storage_root=tmp_path / "parsed",
        document_chunking_enabled=True,
        chunking_service=chunking_service,
        document_embedding_enabled=True,
        embedding_service=embedding_service,
    )

    # 解析作业应保持 succeeded
    stored_parse = session.get(models.DocumentParseJob, job.id)
    assert stored_parse.status == "succeeded"

    # 解析结果应存在
    parsed_docs = session.exec(select(models.ParsedDocument)).all()
    assert len(parsed_docs) == 1

    # 分块作业应保持 succeeded
    chunk_jobs = session.exec(select(chunk_models.DocumentChunkJob)).all()
    assert len(chunk_jobs) == 1
    assert chunk_jobs[0].status == "succeeded"

    # chunks 应可查询（不回滚）
    chunks = session.exec(select(chunk_models.DocumentChunk)).all()
    assert len(chunks) == 3

    # 向量化作业应标记为 failed
    emb_jobs = session.exec(select(emb_models.DocumentEmbeddingJob)).all()
    assert len(emb_jobs) == 1
    emb_job = emb_jobs[0]
    assert emb_job.status == "failed"
    assert emb_job.error_code == "api_error"
    assert "API timeout" in emb_job.error_message

    # 不应持久化向量结果
    embeddings = session.exec(select(emb_models.DocumentEmbedding)).all()
    assert embeddings == []


# ═══════════════════════════════════════════════════════════════════════════
# 10.4  Graceful shutdown 收尾正确标记向量化作业
# ═══════════════════════════════════════════════════════════════════════════


def test_shutdown_marks_incomplete_embedding_jobs_failed(session, tmp_path):
    """shutdown 收尾应将 queued 和 running 作业标记为 process_shutdown。

    已完成作业（succeeded / failed / superseded）不应被修改。
    """
    emb_models = import_module("app.models.document_embedding")
    chunk_models = import_module("app.models.document_chunking")

    _user, _upload, _parse_job, parsed_doc = make_parsed_document_with_segment(
        session, tmp_path / "uploads"
    )

    chunk_job = chunk_models.DocumentChunkJob(
        parsed_document_id=parsed_doc.id,
        owner_user_id=_user.id,
        status="succeeded",
        chunker_name="test",
        chunk_config_json={},
    )
    session.add(chunk_job)
    session.commit()
    session.refresh(chunk_job)

    # 创建五种状态的向量化作业
    jobs_by_status = {}
    for status in ["queued", "running", "succeeded", "failed", "superseded"]:
        job = emb_models.DocumentEmbeddingJob(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed_doc.id,
            owner_user_id=_user.id,
            status=status,
            model="test-model",
            dimensions=2560,
            error_code="api_error" if status == "failed" else None,
            error_message="original error" if status == "failed" else None,
            config_json={},
        )
        session.add(job)
        jobs_by_status[status] = job
    session.commit()
    for job in jobs_by_status.values():
        session.refresh(job)

    embedding_mod = import_module("app.services.document_embedding")
    count = embedding_mod.mark_incomplete_embedding_jobs_failed_for_shutdown(
        session=session,
        reason="signal",
    )

    # 只标记了 queued 和 running 共 2 个
    assert count == 2

    for job in jobs_by_status.values():
        session.refresh(job)

    # queued 和 running 应标记为 process_shutdown
    for status in ["queued", "running"]:
        j = jobs_by_status[status]
        assert j.status == "failed", f"Expected {status} → failed"
        assert j.error_code == "process_shutdown"
        assert "shutdown" in j.error_message.lower()
        assert j.finished_at is not None

    # 已完成作业不应被修改
    assert jobs_by_status["succeeded"].status == "succeeded"
    assert jobs_by_status["succeeded"].error_code is None
    assert jobs_by_status["failed"].status == "failed"
    assert jobs_by_status["failed"].error_code == "api_error"
    assert jobs_by_status["failed"].error_message == "original error"
    assert jobs_by_status["superseded"].status == "superseded"


# ═══════════════════════════════════════════════════════════════════════════
# 10.5  重新向量化端到端流程
# ═══════════════════════════════════════════════════════════════════════════


def test_reembed_end_to_end_flow(session, tmp_path):
    """重新向量化端到端：创建作业 → 后台执行 → 结果持久化 → 旧作业 superseded。"""
    emb_models = import_module("app.models.document_embedding")
    chunk_models = import_module("app.models.document_chunking")

    _user, _upload, _parse_job, parsed_doc = make_parsed_document_with_segment(
        session, tmp_path / "uploads"
    )

    # 创建分块作业和 chunks
    chunk_job = chunk_models.DocumentChunkJob(
        parsed_document_id=parsed_doc.id,
        owner_user_id=_user.id,
        status="succeeded",
        chunker_name="test",
        chunk_config_json={},
    )
    session.add(chunk_job)
    session.commit()
    session.refresh(chunk_job)

    for i in range(2):
        session.add(
            chunk_models.DocumentChunk(
                chunk_job_id=chunk_job.id,
                parsed_document_id=parsed_doc.id,
                owner_user_id=_user.id,
                sequence_index=i,
                text=f"Re-embed chunk {i}",
                token_count=5,
                chunk_type="text",
                source_segment_indices=[0],
            )
        )
    session.commit()

    # 创建旧的 succeeded 向量化作业
    old_job = emb_models.DocumentEmbeddingJob(
        chunk_job_id=chunk_job.id,
        parsed_document_id=parsed_doc.id,
        owner_user_id=_user.id,
        status="succeeded",
        model="old-model",
        dimensions=2560,
        embedding_count=2,
        config_json={"model": "old-model"},
    )
    session.add(old_job)
    session.commit()
    session.refresh(old_job)

    # 创建新的 queued 向量化作业（模拟重新向量化请求）
    new_job = emb_models.DocumentEmbeddingJob(
        chunk_job_id=chunk_job.id,
        parsed_document_id=parsed_doc.id,
        owner_user_id=_user.id,
        status="queued",
        model="new-model",
        dimensions=2560,
        config_json={"model": "new-model"},
    )
    session.add(new_job)
    session.commit()
    session.refresh(new_job)

    # 通过 run_reembed_job 执行重新向量化
    routes_mod = import_module("app.api.routes.document_embedding")
    adapter_mod = import_module("app.services.embedding_adapter")

    class ReembedAdapter:
        def embed(self, texts):
            return [
                adapter_mod.EmbeddingResult(index=i, embedding=[0.5] * 2560)
                for i in range(len(texts))
            ]

    @contextmanager
    def test_session_factory():
        yield session

    routes_mod.run_reembed_job(
        new_job.id,
        session_factory=test_session_factory,
        embedding_adapter=ReembedAdapter(),
        shutdown_state=None,
    )

    # 新作业应成功
    session.refresh(new_job)
    assert new_job.status == "succeeded"
    assert new_job.embedding_count == 2

    # 旧作业应被标记为 superseded
    session.refresh(old_job)
    assert old_job.status == "superseded"

    # 向量结果应按 sequence_index 持久化
    embeddings = session.exec(
        select(emb_models.DocumentEmbedding)
        .where(emb_models.DocumentEmbedding.embedding_job_id == new_job.id)
        .order_by(emb_models.DocumentEmbedding.sequence_index)
    ).all()
    assert len(embeddings) == 2
    assert embeddings[0].sequence_index == 0
    assert embeddings[1].sequence_index == 1
    assert embeddings[0].embedding_json == [0.5] * 2560
    assert embeddings[0].model == "new-model"
