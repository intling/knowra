from collections.abc import Generator
from contextlib import suppress
from importlib import import_module
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from tests.document_chunking_helpers import chunking_session, make_minimal_docling_document
from tests.document_parsing_helpers import SessionFactory, make_uploaded_file, make_user


def make_ready_readiness(tmp_path):
    return SimpleNamespace(
        status="ready",
        docling=SimpleNamespace(
            status="ready",
            artifact_dir=str(tmp_path / "document-models" / "docling"),
            missing_models=[],
        ),
        tokenizer=SimpleNamespace(
            status="ready",
            model_name="Qwen/Qwen2-7B",
            cache_dir=str(tmp_path / "document-models" / "tokenizers"),
            missing_models=[],
        ),
    )


def make_unavailable_readiness():
    return SimpleNamespace(
        status="unavailable",
        docling=SimpleNamespace(
            status="unavailable",
            artifact_dir="storage/document-models/docling",
            missing_models=["layout"],
        ),
        tokenizer=SimpleNamespace(
            status="unavailable",
            model_name="Qwen/Qwen2-7B",
            cache_dir="storage/document-models/tokenizers",
            missing_models=["Qwen/Qwen2-7B"],
        ),
    )


def make_loading_tokenizer_readiness():
    return SimpleNamespace(
        status="loading",
        docling=SimpleNamespace(
            status="ready",
            artifact_dir="storage/document-models/docling",
            missing_models=[],
        ),
        tokenizer=SimpleNamespace(
            status="loading",
            model_name="Qwen/Qwen2-7B",
            cache_dir="storage/document-models/tokenizers",
            missing_models=[],
        ),
    )


@pytest.fixture
def parse_session() -> Generator[Session]:
    import_module("app.models.uploaded_file")
    with suppress(ModuleNotFoundError):
        import_module("app.models.document_parsing")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        yield session


class RecordingParser:
    def __init__(self) -> None:
        self.calls = 0

    def parse(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("模型不可用时不应调用真实 parser")


class RecordingChunker:
    def __init__(self) -> None:
        self.calls = []

    def chunk(self, document):
        self.calls.append(document)
        raise AssertionError("tokenizer 不可用时不应调用真实 chunker")


# 测试 Docling parser 使用启动模型准备目录，而不是旧解析缓存目录。
# 该测试驱动 DoclingParserAdapter 接收 document model artifacts 目录。
def test_docling_parser_adapter_uses_document_model_artifact_dir(monkeypatch, tmp_path) -> None:
    parser = import_module("app.services.document_parser")
    cache_dir = tmp_path / "document-models" / "docling"
    cache_dir.joinpath("docling-project--docling-layout-heron").mkdir(parents=True)
    captured = {}

    import docling.document_converter as document_converter
    from docling.datamodel.base_models import InputFormat

    class FakeDocumentConverter:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

    monkeypatch.setattr(document_converter, "DocumentConverter", FakeDocumentConverter)

    adapter = parser.DoclingParserAdapter(
        ocr_enabled=False,
        max_pages=7,
        docling_artifact_dir=cache_dir,
    )

    converter = adapter._create_converter()

    assert isinstance(converter, FakeDocumentConverter)
    pdf_options = captured["kwargs"]["format_options"][InputFormat.PDF].pipeline_options
    assert pdf_options.artifacts_path == cache_dir


# 测试解析任务在 Docling readiness 不可用时快速失败为 model_unavailable。
# 该测试避免任务进入 Docling 后才发生网络超时或泛化 parse_failed。
def test_run_parse_job_marks_model_unavailable_without_invoking_parser(
    parse_session: Session,
    tmp_path,
) -> None:
    dispatcher_module = import_module("app.services.document_parse_dispatcher")
    models = import_module("app.models.document_parsing")
    user = make_user(parse_session)
    upload = make_uploaded_file(parse_session, tmp_path / "uploads", user)
    job = models.DocumentParseJob(uploaded_file_id=upload.id, owner_user_id=user.id)
    parse_session.add(job)
    parse_session.commit()
    parser = RecordingParser()

    dispatcher_module.run_parse_job(
        job.id,
        session_factory=SessionFactory(parse_session),
        parser=parser,
        upload_storage_root=tmp_path / "uploads",
        artifact_storage_root=tmp_path / "parsed",
        model_readiness=make_unavailable_readiness(),
    )

    stored_job = parse_session.get(models.DocumentParseJob, job.id)
    assert stored_job.status == "failed"
    assert stored_job.error_code == "model_unavailable"
    assert "layout" in stored_job.error_message
    assert parser.calls == 0


# 测试 chunker 运行时使用启动准备的 tokenizer cache 目录。
# 该测试驱动分块适配器从模型 readiness 读取 tokenizer cache，而不是旧解析缓存目录。
def test_docling_chunker_adapter_uses_document_model_tokenizer_cache_dir(tmp_path) -> None:
    module = import_module("app.services.document_chunker")
    tokenizer_cache_dir = str(tmp_path / "document-models" / "tokenizers")
    readiness = make_ready_readiness(tmp_path)
    tokenizer_calls = []

    class FakeHybridChunker:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def chunk(self, _document):
            return [SimpleNamespace(text="Chunk", meta=None)]

        def contextualize(self, chunk):
            return chunk.text

    def tokenizer_factory(**kwargs):
        tokenizer_calls.append(kwargs)
        return SimpleNamespace(count_tokens=lambda text: len(text.split()))

    adapter = module.DoclingChunkerAdapter(
        config=module.DocumentChunkingConfig(tokenizer_model="Qwen/Qwen2-7B"),
        model_readiness=readiness,
        hybrid_chunker_cls=FakeHybridChunker,
        tokenizer_factory=tokenizer_factory,
    )

    adapter.chunk(object())

    assert tokenizer_calls == [
        {
            "model_name": "Qwen/Qwen2-7B",
            "max_tokens": 512,
            "cache_dir": tokenizer_cache_dir,
        }
    ]


# 测试 tokenizer readiness 不可用时分块作业失败为 model_unavailable。
# 该测试确保不会在分块任务中临时访问 Hugging Face 下载 tokenizer。
def test_document_chunking_service_marks_model_unavailable_without_invoking_chunker(
    tmp_path,
) -> None:
    chunking_module = import_module("app.services.document_chunking")
    models = import_module("app.models.document_chunking")
    storage_module = import_module("app.services.document_chunk_storage")
    with chunking_session() as session:
        from tests.document_chunking_helpers import make_parsed_document_with_segment

        _user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session,
            tmp_path / "uploads",
        )
        chunker = RecordingChunker()
        service = chunking_module.DocumentChunkingService(
            session=session,
            chunker=chunker,
            artifact_storage=storage_module.ChunkArtifactStorage(tmp_path / "chunks"),
            config=chunking_module.DocumentChunkingConfig(),
            model_readiness=make_unavailable_readiness(),
        )

        job = service.run_initial_chunking(
            parsed_document=parsed_document,
            transient_docling_document=make_minimal_docling_document(),
        )

        stored_job = session.get(models.DocumentChunkJob, job.id)
        assert stored_job.status == "failed"
        assert stored_job.error_code == "model_unavailable"
        assert "Qwen/Qwen2-7B" in stored_job.error_message
        assert chunker.calls == []


# 测试 tokenizer 仍在内存加载时分块作业快速失败，不调用真实 chunker。
# 该测试覆盖自动分块路径中的 loading 状态错误语义。
def test_document_chunking_service_marks_model_loading_without_invoking_chunker(
    tmp_path,
) -> None:
    chunking_module = import_module("app.services.document_chunking")
    models = import_module("app.models.document_chunking")
    storage_module = import_module("app.services.document_chunk_storage")
    with chunking_session() as session:
        from tests.document_chunking_helpers import make_parsed_document_with_segment

        _user, _upload, _parse_job, parsed_document = make_parsed_document_with_segment(
            session,
            tmp_path / "uploads",
        )
        chunker = RecordingChunker()
        service = chunking_module.DocumentChunkingService(
            session=session,
            chunker=chunker,
            artifact_storage=storage_module.ChunkArtifactStorage(tmp_path / "chunks"),
            config=chunking_module.DocumentChunkingConfig(),
            model_readiness=make_loading_tokenizer_readiness(),
        )

        job = service.run_initial_chunking(
            parsed_document=parsed_document,
            transient_docling_document=make_minimal_docling_document(),
        )

        stored_job = session.get(models.DocumentChunkJob, job.id)
        assert stored_job.status == "failed"
        assert stored_job.error_code == "model_unavailable"
        assert "loading" in stored_job.error_message.lower()
        assert chunker.calls == []
