# 本文件验证文档向量化 SQLModel 的数据库契约。
# 重点覆盖模型注册、字段集合、作业状态枚举、默认值、外键关系和查询索引，防止持久化结构漂移。

from importlib import import_module
from uuid import uuid4

from sqlmodel import SQLModel

EXPECTED_JOB_COLUMNS = {
    "id",
    "chunk_job_id",
    "parsed_document_id",
    "owner_user_id",
    "status",
    "embedder_name",
    "model",
    "dimensions",
    "embedding_count",
    "attempt_count",
    "started_at",
    "finished_at",
    "error_code",
    "error_message",
    "config_json",
    "created_at",
    "updated_at",
}

EXPECTED_EMBEDDING_COLUMNS = {
    "id",
    "embedding_job_id",
    "chunk_id",
    "parsed_document_id",
    "owner_user_id",
    "sequence_index",
    "model",
    "dimensions",
    "embedding_json",
    "token_count",
    "created_at",
}


# 导入模型模块后，SQLModel metadata 必须包含向量化作业表和向量结果表。
# 这是迁移、建表和测试 session 能识别向量化模型的前提。
def test_document_embedding_models_are_registered_with_metadata() -> None:
    models = import_module("app.models.document_embedding")

    assert models.DocumentEmbeddingJob.__tablename__ == "document_embedding_jobs"
    assert models.DocumentEmbedding.__tablename__ == "document_embeddings"
    assert "document_embedding_jobs" in SQLModel.metadata.tables
    assert "document_embeddings" in SQLModel.metadata.tables


# DocumentEmbeddingJob 必须保留作业生命周期、配置快照和错误信息字段。
# 测试还守住五种状态枚举以及按用户、分块作业、解析文档和状态筛选作业所需的索引。
def test_document_embedding_job_model_fields_indexes_and_statuses() -> None:
    models = import_module("app.models.document_embedding")
    table = models.DocumentEmbeddingJob.__table__

    assert set(table.columns.keys()) == EXPECTED_JOB_COLUMNS
    assert {status.value for status in models.DocumentEmbeddingJobStatus} == {
        "queued",
        "running",
        "succeeded",
        "failed",
        "superseded",
    }
    indexed_columns = {column.name for index in table.indexes for column in index.columns}
    assert {"owner_user_id", "chunk_job_id", "parsed_document_id", "status"} <= indexed_columns


# DocumentEmbeddingJob 创建时默认状态必须为 queued，embedder_name 为 openai_compatible，
# embedding_count 和 attempt_count 必须为 0。
def test_document_embedding_job_has_correct_defaults() -> None:
    models = import_module("app.models.document_embedding")

    job = models.DocumentEmbeddingJob(
        chunk_job_id=uuid4(),
        parsed_document_id=uuid4(),
        owner_user_id=uuid4(),
        model="Qwen/Qwen3-Embedding-0.6B",
        dimensions=1024,
    )

    assert job.status == "queued"
    assert job.embedder_name == "openai_compatible"
    assert job.embedding_count == 0
    assert job.attempt_count == 0
    assert job.started_at is None
    assert job.finished_at is None
    assert job.error_code is None
    assert job.error_message is None


# DocumentEmbeddingJob 必需字段（chunk_job_id、parsed_document_id、owner_user_id、
# model、dimensions）必须提供非空值。
def test_document_embedding_job_required_fields_are_not_nullable() -> None:
    models = import_module("app.models.document_embedding")
    columns = models.DocumentEmbeddingJob.__table__.columns

    assert not columns["chunk_job_id"].nullable
    assert not columns["parsed_document_id"].nullable
    assert not columns["owner_user_id"].nullable
    assert not columns["model"].nullable
    assert not columns["dimensions"].nullable


# DocumentEmbeddingJob 的 config_json 必须能保存模型、维度、批次大小和编码格式快照。
def test_document_embedding_job_config_json_snapshot() -> None:
    models = import_module("app.models.document_embedding")

    config_json = {
        "model": "Qwen/Qwen3-Embedding-0.6B",
        "dimensions": 1024,
        "batch_size": 100,
        "encoding_format": "float",
    }

    job = models.DocumentEmbeddingJob(
        chunk_job_id=uuid4(),
        parsed_document_id=uuid4(),
        owner_user_id=uuid4(),
        model="Qwen/Qwen3-Embedding-0.6B",
        dimensions=1024,
        config_json=config_json,
    )

    assert job.config_json == config_json
    assert job.config_json["model"] == "Qwen/Qwen3-Embedding-0.6B"
    assert job.config_json["dimensions"] == 1024
    assert job.config_json["batch_size"] == 100
    assert job.config_json["encoding_format"] == "float"


# DocumentEmbeddingJob 状态必须只接受枚举定义的有效值。
def test_document_embedding_job_status_enum_constraints() -> None:
    models = import_module("app.models.document_embedding")
    valid_statuses = {s.value for s in models.DocumentEmbeddingJobStatus}

    # 直接设置有效状态必须被接受
    for status_value in valid_statuses:
        job = models.DocumentEmbeddingJob(
            chunk_job_id=uuid4(),
            parsed_document_id=uuid4(),
            owner_user_id=uuid4(),
            model="test-model",
            dimensions=1024,
            status=status_value,
        )
        assert job.status == status_value


# DocumentEmbedding 必须保留向量结果、模型信息和来源定位字段。
# 测试还守住它与向量化作业、chunk、解析文档、用户的外键，
# 以及按文档顺序读取和归属过滤所需的索引。
def test_document_embedding_model_fields_foreign_keys_and_indexes() -> None:
    models = import_module("app.models.document_embedding")
    table = models.DocumentEmbedding.__table__

    assert set(table.columns.keys()) == EXPECTED_EMBEDDING_COLUMNS
    foreign_targets = {
        foreign_key.target_fullname
        for column in table.columns
        for foreign_key in column.foreign_keys
    }
    assert "document_embedding_jobs.id" in foreign_targets
    assert "document_chunks.id" in foreign_targets
    assert "parsed_documents.id" in foreign_targets
    assert "users.id" in foreign_targets

    indexed_columns = {tuple(column.name for column in index.columns) for index in table.indexes}
    assert ("embedding_job_id",) in indexed_columns
    assert ("chunk_id",) in indexed_columns
    assert ("owner_user_id",) in indexed_columns
    assert ("parsed_document_id", "sequence_index") in indexed_columns


# DocumentEmbedding 创建时必须能保存完整的向量 JSON 数组、模型名、维度和
# token_count 信息。
def test_document_embedding_creation_with_embedding_json() -> None:
    models = import_module("app.models.document_embedding")

    embedding_vector = [0.123, -0.456, 0.789, 0.0]
    embedding = models.DocumentEmbedding(
        embedding_job_id=uuid4(),
        chunk_id=uuid4(),
        parsed_document_id=uuid4(),
        owner_user_id=uuid4(),
        sequence_index=0,
        model="Qwen/Qwen3-Embedding-0.6B",
        dimensions=len(embedding_vector),
        embedding_json=embedding_vector,
        token_count=42,
    )

    assert embedding.embedding_json == embedding_vector
    assert len(embedding.embedding_json) == 4
    assert embedding.embedding_json[0] == 0.123
    assert embedding.embedding_json[1] == -0.456
    assert embedding.model == "Qwen/Qwen3-Embedding-0.6B"
    assert embedding.dimensions == 4
    assert embedding.token_count == 42
    assert embedding.sequence_index == 0


# DocumentEmbedding 的外键关联必须强制存在。
def test_document_embedding_required_foreign_key_fields_are_not_nullable() -> None:
    models = import_module("app.models.document_embedding")
    columns = models.DocumentEmbedding.__table__.columns

    assert not columns["embedding_job_id"].nullable
    assert not columns["chunk_id"].nullable
    assert not columns["parsed_document_id"].nullable
    assert not columns["owner_user_id"].nullable
    assert not columns["sequence_index"].nullable
    assert not columns["model"].nullable
    assert not columns["dimensions"].nullable
    assert not columns["embedding_json"].nullable
