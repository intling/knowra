from datetime import UTC, datetime
from importlib import import_module
from uuid import uuid4

from sqlmodel import SQLModel

JOB_COLUMNS = {
    "id",
    "uploaded_file_id",
    "owner_user_id",
    "status",
    "parser_name",
    "parser_version",
    "attempt_count",
    "started_at",
    "finished_at",
    "error_code",
    "error_message",
    "created_at",
    "updated_at",
}

PARSED_DOCUMENT_COLUMNS = {
    "id",
    "uploaded_file_id",
    "parse_job_id",
    "owner_user_id",
    "source_checksum_sha256",
    "markdown_storage_key",
    "text_storage_key",
    "docling_json_storage_key",
    "title",
    "page_count",
    "metadata_json",
    "created_at",
}

SEGMENT_COLUMNS = {
    "id",
    "parsed_document_id",
    "owner_user_id",
    "sequence_index",
    "segment_type",
    "page_no",
    "heading_path",
    "text",
    "metadata_json",
    "created_at",
}


def get_models_module():
    return import_module("app.models.document_parsing")


# 测试解析模型被导入后会注册到 SQLModel metadata，
# 让服务测试和 Alembic metadata 都能发现三张表。
def test_document_parsing_models_register_expected_tables_and_columns() -> None:
    get_models_module()

    job_table = SQLModel.metadata.tables["document_parse_jobs"]
    parsed_table = SQLModel.metadata.tables["parsed_documents"]
    segment_table = SQLModel.metadata.tables["document_segments"]

    assert set(job_table.columns.keys()) == JOB_COLUMNS
    assert set(parsed_table.columns.keys()) == PARSED_DOCUMENT_COLUMNS
    assert set(segment_table.columns.keys()) == SEGMENT_COLUMNS

    assert "uploaded_files.id" in {
        foreign_key.target_fullname
        for foreign_key in job_table.columns["uploaded_file_id"].foreign_keys
    }
    assert "users.id" in {
        foreign_key.target_fullname
        for foreign_key in job_table.columns["owner_user_id"].foreign_keys
    }
    assert "document_parse_jobs.id" in {
        foreign_key.target_fullname
        for foreign_key in parsed_table.columns["parse_job_id"].foreign_keys
    }
    assert "parsed_documents.id" in {
        foreign_key.target_fullname
        for foreign_key in segment_table.columns["parsed_document_id"].foreign_keys
    }


# 测试作业状态和时间字段默认值满足异步生命周期契约。
def test_document_parse_job_defaults_to_queued_status() -> None:
    models = get_models_module()
    uploaded_file_id = uuid4()
    owner_user_id = uuid4()

    job = models.DocumentParseJob(
        uploaded_file_id=uploaded_file_id,
        owner_user_id=owner_user_id,
    )

    assert job.status == "queued"
    assert job.parser_name == "docling"
    assert job.attempt_count == 0
    assert job.started_at is None
    assert job.finished_at is None
    assert job.error_code is None
    assert job.error_message is None
    assert job.created_at.tzinfo == UTC
    assert job.updated_at.tzinfo == UTC


# 测试解析结果和结构片段模型能表达解析产物、页数和来源位置。
def test_parsed_document_and_segment_models_hold_artifact_and_location_metadata() -> None:
    models = get_models_module()
    created_at = datetime(2026, 6, 5, tzinfo=UTC)

    parsed = models.ParsedDocument(
        uploaded_file_id=uuid4(),
        parse_job_id=uuid4(),
        owner_user_id=uuid4(),
        source_checksum_sha256="a" * 64,
        markdown_storage_key="parsed/u/f/j/content.md",
        text_storage_key="parsed/u/f/j/content.txt",
        docling_json_storage_key="parsed/u/f/j/docling.json",
        title="Lecture",
        page_count=3,
        metadata_json={"parser": "docling"},
        created_at=created_at,
    )
    segment = models.DocumentSegment(
        parsed_document_id=uuid4(),
        owner_user_id=parsed.owner_user_id,
        sequence_index=0,
        segment_type="paragraph",
        page_no=1,
        heading_path=["Lecture"],
        text="Key idea",
        metadata_json={"docling_ref": "#/texts/0"},
        created_at=created_at,
    )

    assert parsed.page_count == 3
    assert parsed.metadata_json["parser"] == "docling"
    assert segment.sequence_index == 0
    assert segment.heading_path == ["Lecture"]
    assert segment.metadata_json["docling_ref"] == "#/texts/0"
