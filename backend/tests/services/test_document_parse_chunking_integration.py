# 本文件验证解析调度器与分块服务的衔接。
# 解析成功后应把内存 transient DoclingDocument 直接交给自动分块，且分块失败不影响解析成功。

from collections.abc import Generator
from contextlib import suppress
from importlib import import_module

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from tests.document_chunking_helpers import make_minimal_docling_document
from tests.document_parsing_helpers import (
    ParsedPayloadFactory,
    SessionFactory,
    make_uploaded_file,
    make_user,
)


@pytest.fixture
# 提供解析调度器测试专用内存数据库，并注册上传和解析模型。
# 这些测试聚焦 parse job 状态和分块调用，不依赖真实数据库。
def session() -> Generator[Session]:
    import_module("app.models.uploaded_file")
    with suppress(ModuleNotFoundError):
        import_module("app.models.document_parsing")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as test_session:
        yield test_session


class ParserReturningTransientResult:
    # 构造包含 persistent payload 与可选 transient 文档的解析结果。
    # 用于模拟 Docling 解析成功后的返回契约。
    def __init__(self, transient_docling_document=None) -> None:
        parser = import_module("app.services.document_parser")
        self.result = parser.ParsedDocumentResult(
            persistent_payload=ParsedPayloadFactory().make(),
            transient_docling_document=transient_docling_document,
        )

    # 无论输入文件是什么都返回预设结果。
    # 这样测试只观察调度器如何处理解析结果。
    def parse(self, *_args, **_kwargs):
        return self.result


class CapturingChunkingService:
    # 记录自动分块调用，并可配置为抛错。
    # 用于验证调度器成功、禁用和失败容错分支。
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = []

    # 捕获 parsed_document 与 transient_docling_document。
    # 测试用它确认调度器传递的是刚解析出的同一个内存对象。
    def run_initial_chunking(self, *, parsed_document, transient_docling_document):
        self.calls.append(
            {
                "parsed_document": parsed_document,
                "transient_docling_document": transient_docling_document,
            }
        )
        if self.error is not None:
            raise self.error


class InspectingChunkingService:
    # 在自动分块开始时重新读取 parse job。
    # 用于验证前端轮询能在分块耗时或网络阻塞前看到解析已成功。
    def __init__(self, session, parse_job_id) -> None:
        self.session = session
        self.parse_job_id = parse_job_id
        self.seen_status = None
        self.seen_finished_at = None

    def run_initial_chunking(self, *, parsed_document, transient_docling_document):
        models = import_module("app.models.document_parsing")
        self.session.expire_all()
        stored_job = self.session.get(models.DocumentParseJob, self.parse_job_id)
        self.seen_status = stored_job.status
        self.seen_finished_at = stored_job.finished_at


# 种下 queued parse job 及其上传文件。
# 这是 run_parse_job 后台任务的最小输入。
def make_parse_job(session, tmp_path):
    models = import_module("app.models.document_parsing")
    user = make_user(session)
    upload = make_uploaded_file(session, tmp_path / "uploads", user)
    job = models.DocumentParseJob(uploaded_file_id=upload.id, owner_user_id=user.id)
    session.add(job)
    session.commit()
    session.refresh(job)
    return models, job


# 解析返回 transient 文档且自动分块启用时，run_parse_job 应保持解析成功。
# 测试确认同一个 DoclingDocument 对象会被传给分块服务。
def test_run_parse_job_passes_same_transient_docling_document_to_chunking_service(
    session,
    tmp_path,
) -> None:
    dispatcher = import_module("app.services.document_parse_dispatcher")
    models, job = make_parse_job(session, tmp_path)
    transient_doc = make_minimal_docling_document()
    chunking_service = CapturingChunkingService()

    dispatcher.run_parse_job(
        job.id,
        session_factory=SessionFactory(session),
        parser=ParserReturningTransientResult(transient_doc),
        upload_storage_root=tmp_path / "uploads",
        artifact_storage_root=tmp_path / "parsed",
        document_chunking_enabled=True,
        chunking_service=chunking_service,
    )

    stored_job = session.get(models.DocumentParseJob, job.id)
    parsed_document = session.exec(select(models.ParsedDocument)).one()
    assert stored_job.status == "succeeded"
    assert chunking_service.calls == [
        {
            "parsed_document": parsed_document,
            "transient_docling_document": transient_doc,
        }
    ]


# 自动分块可能因为 tokenizer 下载等网络因素变慢。
# 解析结果持久化后，parse job 应先变为 succeeded，让前端切换到分块阶段。
def test_run_parse_job_marks_parse_succeeded_before_auto_chunking_starts(
    session,
    tmp_path,
) -> None:
    dispatcher = import_module("app.services.document_parse_dispatcher")
    models, job = make_parse_job(session, tmp_path)
    chunking_service = InspectingChunkingService(session, job.id)

    dispatcher.run_parse_job(
        job.id,
        session_factory=SessionFactory(session),
        parser=ParserReturningTransientResult(make_minimal_docling_document()),
        upload_storage_root=tmp_path / "uploads",
        artifact_storage_root=tmp_path / "parsed",
        document_chunking_enabled=True,
        chunking_service=chunking_service,
    )

    stored_job = session.get(models.DocumentParseJob, job.id)
    assert chunking_service.seen_status == "succeeded"
    assert chunking_service.seen_finished_at is not None
    assert stored_job.status == "succeeded"


# 自动分块禁用时，run_parse_job 只应完成解析作业。
# 测试确认不会创建或调用分块流程。
def test_run_parse_job_does_not_create_chunk_job_when_chunking_disabled(session, tmp_path) -> None:
    dispatcher = import_module("app.services.document_parse_dispatcher")
    models, job = make_parse_job(session, tmp_path)
    chunking_service = CapturingChunkingService()

    dispatcher.run_parse_job(
        job.id,
        session_factory=SessionFactory(session),
        parser=ParserReturningTransientResult(make_minimal_docling_document()),
        upload_storage_root=tmp_path / "uploads",
        artifact_storage_root=tmp_path / "parsed",
        document_chunking_enabled=False,
        chunking_service=chunking_service,
    )

    stored_job = session.get(models.DocumentParseJob, job.id)
    assert stored_job.status == "succeeded"
    assert chunking_service.calls == []


# 自动分块抛错时，run_parse_job 仍应保留解析成功和 parsed_documents。
# 这个测试防止分块失败污染解析结果。
def test_run_parse_job_keeps_parse_success_when_auto_chunking_fails(session, tmp_path) -> None:
    dispatcher = import_module("app.services.document_parse_dispatcher")
    models, job = make_parse_job(session, tmp_path)
    chunking_service = CapturingChunkingService(error=RuntimeError("chunking failed"))

    dispatcher.run_parse_job(
        job.id,
        session_factory=SessionFactory(session),
        parser=ParserReturningTransientResult(make_minimal_docling_document()),
        upload_storage_root=tmp_path / "uploads",
        artifact_storage_root=tmp_path / "parsed",
        document_chunking_enabled=True,
        chunking_service=chunking_service,
    )

    stored_job = session.get(models.DocumentParseJob, job.id)
    parsed_documents = session.exec(select(models.ParsedDocument)).all()
    assert stored_job.status == "succeeded"
    assert len(parsed_documents) == 1
