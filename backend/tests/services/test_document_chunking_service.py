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


# 同一解析结果已有 running 作业时，rechunk 应抛出冲突并带回已有作业。
# 这个测试防止并发重分块造成重复作业。
def test_rechunk_rejects_running_job_with_conflict(tmp_path) -> None:
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

        try:
            service.rechunk(parsed_document_id=parsed_document.id, current_user=user)
        except module.DocumentChunkConflictError as exc:
            assert exc.job.id == running_job.id
        else:
            raise AssertionError("Expected running chunk job conflict")


# 重分块成功写入新 chunks 后，才应把旧 succeeded 作业标记为 superseded。
# 这样新分块失败时仍能保留旧的可用结果。
def test_rechunk_success_supersedes_old_job_only_after_new_chunks_are_saved(tmp_path) -> None:
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
        service = make_service(module, session, tmp_path)

        new_job = service.rechunk(
            parsed_document_id=parsed_document.id,
            current_user=user,
            parser=SimpleNamespace(parse=lambda *_args, **_kwargs: make_minimal_docling_document()),
        )

        session.refresh(old_job)
        assert new_job.status == "succeeded"
        assert old_job.status == "superseded"
