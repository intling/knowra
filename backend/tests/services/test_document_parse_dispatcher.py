from collections.abc import Generator
from contextlib import suppress
from importlib import import_module
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from tests.document_parsing_helpers import (
    ParsedPayloadFactory,
    SessionFactory,
    make_uploaded_file,
    make_user,
)


def get_dispatcher_module():
    return import_module("app.services.document_parse_dispatcher")


def get_models_module():
    return import_module("app.models.document_parsing")


@pytest.fixture
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


class FakeParser:
    def __init__(self, payload=None, error: Exception | None = None) -> None:
        self.payload = payload or ParsedPayloadFactory().make()
        self.error = error
        self.calls = 0

    def parse(self, *_args, **_kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.payload


def make_loading_readiness():
    return SimpleNamespace(
        status="loading",
        docling=SimpleNamespace(status="loading", missing_models=[]),
        tokenizer=SimpleNamespace(status="ready", missing_models=[]),
    )


def make_ready_readiness_with_converter(converter):
    return SimpleNamespace(
        status="ready",
        docling=SimpleNamespace(
            status="ready",
            artifact_dir="storage/document-models/docling",
            missing_models=[],
            resource=converter,
        ),
        tokenizer=SimpleNamespace(status="ready", missing_models=[]),
    )


# 测试 BackgroundTasks dispatcher 成功注册 run_parse_job(job_id)。
def test_background_tasks_dispatcher_registers_run_parse_job() -> None:
    dispatcher_module = get_dispatcher_module()
    background_tasks = BackgroundTasks()
    job_id = "00000000-0000-0000-0000-000000000123"

    dispatcher = dispatcher_module.BackgroundTasksParseJobDispatcher(background_tasks)
    dispatcher.enqueue(job_id)

    assert len(background_tasks.tasks) == 1
    task = background_tasks.tasks[0]
    assert task.func is dispatcher_module.run_parse_job
    assert task.args == (job_id,)


# 测试后台任务重新读取数据库作业，成功后保存解析结果并写回 succeeded。
def test_run_parse_job_persists_success_result_and_marks_job_succeeded(
    session: Session,
    tmp_path,
) -> None:
    dispatcher_module = get_dispatcher_module()
    models = get_models_module()
    user = make_user(session)
    upload = make_uploaded_file(session, tmp_path / "uploads", user)
    job = models.DocumentParseJob(uploaded_file_id=upload.id, owner_user_id=user.id)
    session.add(job)
    session.commit()
    session.refresh(job)
    parser = FakeParser()

    dispatcher_module.run_parse_job(
        job.id,
        session_factory=SessionFactory(session),
        parser=parser,
        upload_storage_root=tmp_path / "uploads",
        artifact_storage_root=tmp_path / "parsed",
    )

    stored_job = session.get(models.DocumentParseJob, job.id)
    parsed_document = session.exec(select(models.ParsedDocument)).one()
    segments = session.exec(select(models.DocumentSegment)).all()
    assert stored_job.status == "succeeded"
    assert stored_job.started_at is not None
    assert stored_job.finished_at is not None
    assert parsed_document.parse_job_id == job.id
    assert parsed_document.uploaded_file_id == upload.id
    assert len(segments) == 1
    assert parser.calls == 1


# 测试后台任务失败时写回 failed、错误码和错误信息。
def test_run_parse_job_marks_job_failed_when_parser_raises(session: Session, tmp_path) -> None:
    dispatcher_module = get_dispatcher_module()
    parser_module = import_module("app.services.document_parser")
    models = get_models_module()
    user = make_user(session)
    upload = make_uploaded_file(session, tmp_path / "uploads", user)
    job = models.DocumentParseJob(uploaded_file_id=upload.id, owner_user_id=user.id)
    session.add(job)
    session.commit()
    parser = FakeParser(error=parser_module.DocumentParseError("parse failed"))

    dispatcher_module.run_parse_job(
        job.id,
        session_factory=SessionFactory(session),
        parser=parser,
        upload_storage_root=tmp_path / "uploads",
        artifact_storage_root=tmp_path / "parsed",
    )

    stored_job = session.get(models.DocumentParseJob, job.id)
    assert stored_job.status == "failed"
    assert stored_job.error_code == "parse_failed"
    assert "parse failed" in stored_job.error_message


# 测试后台任务会把没有提取出正文的解析结果视为失败，避免空 PDF 被标记为成功。
def test_run_parse_job_marks_job_failed_when_parser_returns_empty_content(
    session: Session,
    tmp_path,
) -> None:
    dispatcher_module = get_dispatcher_module()
    parser_module = import_module("app.services.document_parser")
    models = get_models_module()
    user = make_user(session)
    upload = make_uploaded_file(session, tmp_path / "uploads", user)
    job = models.DocumentParseJob(uploaded_file_id=upload.id, owner_user_id=user.id)
    session.add(job)
    session.commit()
    parser = FakeParser(
        payload=parser_module.ParsedDocumentPayload(
            markdown="",
            text="",
            docling_json={"content": ""},
            segments=[],
        )
    )

    dispatcher_module.run_parse_job(
        job.id,
        session_factory=SessionFactory(session),
        parser=parser,
        upload_storage_root=tmp_path / "uploads",
        artifact_storage_root=tmp_path / "parsed",
    )

    stored_job = session.get(models.DocumentParseJob, job.id)
    parsed_documents = session.exec(select(models.ParsedDocument)).all()
    assert stored_job.status == "failed"
    assert stored_job.error_code == "parse_failed"
    assert "no text content" in stored_job.error_message
    assert parsed_documents == []


@pytest.mark.parametrize("status", ["running", "succeeded", "failed", "cancelled"])
# 测试任务入口幂等跳过非 queued 作业，避免重复解析。
def test_run_parse_job_skips_jobs_that_are_not_queued(
    session: Session,
    tmp_path,
    status: str,
) -> None:
    dispatcher_module = get_dispatcher_module()
    models = get_models_module()
    user = make_user(session)
    upload = make_uploaded_file(session, tmp_path / "uploads", user)
    job = models.DocumentParseJob(
        uploaded_file_id=upload.id,
        owner_user_id=user.id,
        status=status,
    )
    session.add(job)
    session.commit()
    parser = FakeParser()

    dispatcher_module.run_parse_job(
        job.id,
        session_factory=SessionFactory(session),
        parser=parser,
        upload_storage_root=tmp_path / "uploads",
        artifact_storage_root=tmp_path / "parsed",
    )

    stored_job = session.get(models.DocumentParseJob, job.id)
    assert stored_job.status == status
    assert parser.calls == 0


# 测试 Docling 模型 loading 时后台 PDF 解析作业快速失败，不调用 parser。
# 该测试覆盖绕过 API 直接执行后台任务的保护分支。
def test_run_parse_job_marks_model_unavailable_when_docling_models_are_loading(
    session: Session,
    tmp_path,
) -> None:
    dispatcher_module = get_dispatcher_module()
    models = get_models_module()
    user = make_user(session)
    upload = make_uploaded_file(session, tmp_path / "uploads", user)
    job = models.DocumentParseJob(uploaded_file_id=upload.id, owner_user_id=user.id)
    session.add(job)
    session.commit()
    parser = FakeParser()

    dispatcher_module.run_parse_job(
        job.id,
        session_factory=SessionFactory(session),
        parser=parser,
        upload_storage_root=tmp_path / "uploads",
        artifact_storage_root=tmp_path / "parsed",
        model_readiness=make_loading_readiness(),
    )

    stored_job = session.get(models.DocumentParseJob, job.id)
    assert stored_job.status == "failed"
    assert stored_job.error_code == "model_unavailable"
    assert "loading" in stored_job.error_message.lower()
    assert parser.calls == 0


# 测试 runtime ready 时后台解析会把预加载 converter 注入 DoclingParserAdapter。
# 该测试确保预加载完成后不会重新初始化 Docling PDF pipeline。
def test_run_parse_job_reuses_preloaded_docling_converter(
    monkeypatch,
    session: Session,
    tmp_path,
) -> None:
    dispatcher_module = get_dispatcher_module()
    parser_module = import_module("app.services.document_parser")
    models = get_models_module()
    user = make_user(session)
    upload = make_uploaded_file(session, tmp_path / "uploads", user)
    job = models.DocumentParseJob(uploaded_file_id=upload.id, owner_user_id=user.id)
    session.add(job)
    session.commit()
    preloaded_converter = object()
    captured = {}

    class FakeDoclingParserAdapter:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        def parse(self, *_args, **_kwargs):
            return parser_module.ParsedDocumentResult(
                persistent_payload=ParsedPayloadFactory().make()
            )

    monkeypatch.setattr(dispatcher_module, "DoclingParserAdapter", FakeDoclingParserAdapter)

    dispatcher_module.run_parse_job(
        job.id,
        session_factory=SessionFactory(session),
        upload_storage_root=tmp_path / "uploads",
        artifact_storage_root=tmp_path / "parsed",
        model_readiness=make_ready_readiness_with_converter(preloaded_converter),
    )

    stored_job = session.get(models.DocumentParseJob, job.id)
    assert stored_job.status == "succeeded"
    assert captured["kwargs"]["converter"] is preloaded_converter
