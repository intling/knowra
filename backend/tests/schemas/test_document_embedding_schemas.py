# 本文件验证文档向量化 Pydantic schema 的序列化契约。
# 重点覆盖响应 schema 字段完整性、日期序列化格式、
# ReEmbedRequest 可选字段行为和分页响应结构。

from datetime import UTC, datetime
from uuid import uuid4

from app.schemas.document_embedding import (
    EmbeddingConflictResponse,
    EmbeddingJobResponse,
    EmbeddingPageResponse,
    EmbeddingResponse,
    ReEmbedRequest,
)


# EmbeddingJobResponse 必须包含 spec 要求的所有字段，
# 并能从模型数据正确序列化。
def test_embedding_job_response_includes_all_expected_fields() -> None:
    now = datetime(2026, 7, 16, 12, 0, 0, tzinfo=UTC)
    job_id = uuid4()
    chunk_job_id = uuid4()
    parsed_doc_id = uuid4()
    owner_id = uuid4()

    response = EmbeddingJobResponse(
        id=job_id,
        chunk_job_id=chunk_job_id,
        parsed_document_id=parsed_doc_id,
        owner_user_id=owner_id,
        status="succeeded",
        embedder_name="openai_compatible",
        model="Qwen/Qwen3-Embedding-4B",
        dimensions=2560,
        embedding_count=50,
        attempt_count=1,
        started_at=now,
        finished_at=now,
        error_code=None,
        error_message=None,
        config_json={"model": "Qwen/Qwen3-Embedding-4B", "dimensions": 2560},
        created_at=now,
        updated_at=now,
    )

    data = response.model_dump(mode="json")
    assert data["id"] == str(job_id)
    assert data["chunk_job_id"] == str(chunk_job_id)
    assert data["parsed_document_id"] == str(parsed_doc_id)
    assert data["owner_user_id"] == str(owner_id)
    assert data["status"] == "succeeded"
    assert data["embedder_name"] == "openai_compatible"
    assert data["model"] == "Qwen/Qwen3-Embedding-4B"
    assert data["dimensions"] == 2560
    assert data["embedding_count"] == 50
    assert data["attempt_count"] == 1
    assert data["error_code"] is None
    assert data["error_message"] is None
    assert data["config_json"] == {"model": "Qwen/Qwen3-Embedding-4B", "dimensions": 2560}


# EmbeddingJobResponse 的 datetime 字段必须序列化为 ISO 8601 格式并以 Z 结尾。
def test_embedding_job_response_serializes_datetime_with_z_suffix() -> None:
    now = datetime(2026, 7, 16, 12, 0, 0, tzinfo=UTC)

    response = EmbeddingJobResponse(
        id=uuid4(),
        chunk_job_id=uuid4(),
        parsed_document_id=uuid4(),
        owner_user_id=uuid4(),
        status="queued",
        embedder_name="openai_compatible",
        model="test-model",
        dimensions=2560,
        embedding_count=0,
        attempt_count=0,
        started_at=None,
        finished_at=None,
        error_code=None,
        error_message=None,
        config_json=None,
        created_at=now,
        updated_at=now,
    )

    data = response.model_dump(mode="json")
    assert data["created_at"].endswith("Z")
    assert data["updated_at"].endswith("Z")
    assert data["started_at"] is None
    assert data["finished_at"] is None


# UtcDateTime 对 naive datetime（无时区）按 UTC 处理并序列化为 Z。
# 这是防御性行为：项目中所有 datetime 均通过 utc_now() 创建为 UTC，
# 但 SQLite 测试数据库不支持时区，回读时 tzinfo 会丢失。
# 此行为确保从数据库读取的 datetime 也能正确序列化。
def test_embedding_job_response_handles_naive_datetime_as_utc() -> None:
    naive = datetime(2026, 7, 16, 12, 0, 0)

    response = EmbeddingJobResponse(
        id=uuid4(),
        chunk_job_id=uuid4(),
        parsed_document_id=uuid4(),
        owner_user_id=uuid4(),
        status="running",
        embedder_name="openai_compatible",
        model="test-model",
        dimensions=2560,
        embedding_count=0,
        attempt_count=0,
        started_at=naive,
        finished_at=None,
        error_code=None,
        error_message=None,
        config_json=None,
        created_at=naive,
        updated_at=naive,
    )

    data = response.model_dump(mode="json")
    assert data["started_at"].endswith("Z")
    assert data["created_at"].endswith("Z")
    assert data["updated_at"].endswith("Z")


# EmbeddingResponse 必须包含 spec 要求的所有字段，包括完整的 embedding_json 数组。
def test_embedding_response_includes_all_expected_fields() -> None:
    now = datetime(2026, 7, 16, 12, 0, 0, tzinfo=UTC)
    embedding_vector = [0.1, 0.2, 0.3, -0.1, -0.2]

    response = EmbeddingResponse(
        id=uuid4(),
        chunk_id=uuid4(),
        embedding_job_id=uuid4(),
        sequence_index=0,
        model="Qwen/Qwen3-Embedding-4B",
        dimensions=len(embedding_vector),
        embedding_json=embedding_vector,
        token_count=42,
        created_at=now,
    )

    data = response.model_dump(mode="json")
    assert data["embedding_json"] == embedding_vector
    assert len(data["embedding_json"]) == 5
    assert data["dimensions"] == 5
    assert data["model"] == "Qwen/Qwen3-Embedding-4B"
    assert data["token_count"] == 42
    assert data["sequence_index"] == 0
    assert data["created_at"].endswith("Z")


# EmbeddingResponse 的 created_at 必须序列化为 ISO 8601 格式并以 Z 结尾。
def test_embedding_response_serializes_created_at_with_z_suffix() -> None:
    now = datetime(2026, 7, 16, 12, 0, 0, tzinfo=UTC)

    response = EmbeddingResponse(
        id=uuid4(),
        chunk_id=uuid4(),
        embedding_job_id=uuid4(),
        sequence_index=1,
        model="test-model",
        dimensions=2560,
        embedding_json=[0.0],
        token_count=1,
        created_at=now,
    )

    data = response.model_dump(mode="json")
    assert data["created_at"].endswith("Z")


# ReEmbedRequest 的 model 和 dimensions 字段必须为可选，不传时使用默认值。
def test_reembed_request_optional_fields() -> None:
    # 不传任何字段
    request = ReEmbedRequest()
    assert request.model is None
    assert request.dimensions is None

    # 只传 model
    request = ReEmbedRequest(model="custom-model")
    assert request.model == "custom-model"
    assert request.dimensions is None

    # 只传 dimensions
    request = ReEmbedRequest(dimensions=512)
    assert request.model is None
    assert request.dimensions == 512

    # 同时传
    request = ReEmbedRequest(model="custom-model", dimensions=768)
    assert request.model == "custom-model"
    assert request.dimensions == 768


# EmbeddingPageResponse 必须包含分页信息和 items 列表。
def test_embedding_page_response_structure() -> None:
    now = datetime(2026, 7, 16, 12, 0, 0, tzinfo=UTC)
    items = [
        EmbeddingResponse(
            id=uuid4(),
            chunk_id=uuid4(),
            embedding_job_id=uuid4(),
            sequence_index=i,
            model="test-model",
            dimensions=2560,
            embedding_json=[0.1 * i],
            token_count=10,
            created_at=now,
        )
        for i in range(3)
    ]

    page = EmbeddingPageResponse(
        items=items,
        total=10,
        offset=0,
        limit=3,
    )

    data = page.model_dump(mode="json")
    assert len(data["items"]) == 3
    assert data["total"] == 10
    assert data["offset"] == 0
    assert data["limit"] == 3


# EmbeddingPageResponse 的 items 为空列表也是合法的（无向量结果）。
def test_embedding_page_response_with_empty_items() -> None:
    page = EmbeddingPageResponse(
        items=[],
        total=0,
        offset=0,
        limit=10,
    )

    data = page.model_dump(mode="json")
    assert data["items"] == []
    assert data["total"] == 0


# EmbeddingConflictResponse 必须包含 detail 消息和冲突的作业信息。
def test_embedding_conflict_response_structure() -> None:
    now = datetime(2026, 7, 16, 12, 0, 0, tzinfo=UTC)
    job = EmbeddingJobResponse(
        id=uuid4(),
        chunk_job_id=uuid4(),
        parsed_document_id=uuid4(),
        owner_user_id=uuid4(),
        status="running",
        embedder_name="openai_compatible",
        model="test-model",
        dimensions=2560,
        embedding_count=0,
        attempt_count=0,
        started_at=now,
        finished_at=None,
        error_code=None,
        error_message=None,
        config_json=None,
        created_at=now,
        updated_at=now,
    )

    conflict = EmbeddingConflictResponse(
        detail="A running embedding job already exists for this chunk job",
        job=job,
    )

    data = conflict.model_dump(mode="json")
    assert data["detail"] == "A running embedding job already exists for this chunk job"
    assert data["job"]["id"] == str(job.id)
    assert data["job"]["status"] == "running"
