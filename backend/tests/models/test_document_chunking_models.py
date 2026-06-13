# 本文件验证文档分块 SQLModel 的数据库契约。
# 重点覆盖模型注册、字段集合、作业状态枚举、外键关系和查询索引，防止持久化结构漂移。

from importlib import import_module

from sqlmodel import SQLModel

EXPECTED_JOB_COLUMNS = {
    "id",
    "parsed_document_id",
    "owner_user_id",
    "status",
    "chunker_name",
    "chunker_version",
    "chunk_config_json",
    "chunk_count",
    "attempt_count",
    "started_at",
    "finished_at",
    "error_code",
    "error_message",
    "created_at",
    "updated_at",
}

EXPECTED_CHUNK_COLUMNS = {
    "id",
    "chunk_job_id",
    "parsed_document_id",
    "owner_user_id",
    "sequence_index",
    "text",
    "text_storage_key",
    "contextualized_text",
    "contextualized_text_storage_key",
    "token_count",
    "heading_path",
    "page_numbers",
    "chunk_type",
    "source_segment_indices",
    "metadata_json",
    "created_at",
}


# 导入模型模块后，SQLModel metadata 必须包含作业表和 chunk 表。
# 这是迁移、建表和测试 session 能识别分块模型的前提。
def test_document_chunking_models_are_registered_with_metadata() -> None:
    models = import_module("app.models.document_chunking")

    assert models.DocumentChunkJob.__tablename__ == "document_chunk_jobs"
    assert models.DocumentChunk.__tablename__ == "document_chunks"
    assert "document_chunk_jobs" in SQLModel.metadata.tables
    assert "document_chunks" in SQLModel.metadata.tables


# DocumentChunkJob 必须保留作业生命周期、配置快照和错误信息字段。
# 测试还守住五种状态枚举以及按用户、解析文档和状态筛选作业所需的索引。
def test_document_chunk_job_model_fields_indexes_and_statuses() -> None:
    models = import_module("app.models.document_chunking")
    table = models.DocumentChunkJob.__table__

    assert set(table.columns.keys()) == EXPECTED_JOB_COLUMNS
    assert {status.value for status in models.DocumentChunkJobStatus} == {
        "queued",
        "running",
        "succeeded",
        "failed",
        "superseded",
    }
    indexed_columns = {column.name for index in table.indexes for column in index.columns}
    assert {"owner_user_id", "parsed_document_id", "status"} <= indexed_columns


# DocumentChunk 必须保留 chunk 内容、来源定位和元数据字段。
# 测试还守住它与作业、解析文档、用户的外键，以及按文档顺序读取所需的索引。
def test_document_chunk_model_fields_foreign_keys_and_indexes() -> None:
    models = import_module("app.models.document_chunking")
    table = models.DocumentChunk.__table__

    assert set(table.columns.keys()) == EXPECTED_CHUNK_COLUMNS
    foreign_targets = {
        foreign_key.target_fullname
        for column in table.columns
        for foreign_key in column.foreign_keys
    }
    assert "document_chunk_jobs.id" in foreign_targets
    assert "parsed_documents.id" in foreign_targets
    assert "users.id" in foreign_targets

    indexed_columns = {tuple(column.name for column in index.columns) for index in table.indexes}
    assert ("chunk_job_id",) in indexed_columns
    assert ("parsed_document_id",) in indexed_columns
    assert ("owner_user_id",) in indexed_columns
    assert ("parsed_document_id", "sequence_index") in indexed_columns
