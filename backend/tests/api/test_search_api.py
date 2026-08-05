# =========================================================================
# 本文件验证 POST /api/search API 端点的集成行为。
# 覆盖正常搜索+生成、无向量数据（404）、参数校验失败（422）、
# 嵌入失败（502）、chat 禁用（503）。
#
# TDD 红阶段：API 路由和路由注册均未实现，测试预期失败。
# =========================================================================

from collections.abc import Generator
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db.session import get_session
from app.main import app

# ── helpers ──────────────────────────────────────────────────────────────


def make_fake_embedding_adapter(
    *,
    vector_dims: int = 2560,
    model: str = "test-embed-model",
    raise_error: Exception | None = None,
):
    """Create a fake EmbeddingAdapter.

    When *raise_error* is set, ``embed_single`` will raise it, simulating
    an embedding API failure.
    """
    adapter = MagicMock()
    adapter.config = SimpleNamespace(model=model, dimensions=vector_dims)
    if raise_error:
        adapter.embed_single = MagicMock(side_effect=raise_error)
    else:
        result = SimpleNamespace(embedding=[0.1] * vector_dims)
        adapter.embed_single = MagicMock(return_value=result)
    return adapter


def make_fake_chat_adapter(*, content: str = "AI 生成的回答。", model: str = "test-chat-model"):
    """Create a fake ChatAdapter."""
    chat_module = import_module("app.services.chat_adapter")
    adapter = MagicMock()
    adapter.config = SimpleNamespace(model=model)
    adapter.generate = MagicMock(
        return_value=chat_module.ChatResult(
            content=content,
            model=model,
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
    )
    return adapter


def make_fake_chat_config(*, model: str = "test-chat-model", **overrides):
    """Build a fake ChatConfig."""
    defaults = {
        "api_base_url": "https://test-api.example.com/v1",
        "api_key": "sk-test-key",
        "model": model,
        "temperature": 0.1,
        "max_tokens": 1024,
        "request_timeout": 30.0,
        "max_retries": 3,
    }
    defaults.update(overrides)
    chat_config_module = import_module("app.services.chat_config")
    return chat_config_module.ChatConfig(**defaults)


def make_fake_session(*, total_embedding_count: int = 1, rows: list | None = None):
    """Create a fake SQLModel Session for the search query.

    ``total_embedding_count`` controls what ``SELECT COUNT(*)`` returns
    (0 → simulates "no vector data").
    """
    session = MagicMock()
    if rows is None:
        rows = []
    if total_embedding_count == 0:
        rows = []

    mock_result = MagicMock()
    mock_result.all.return_value = rows
    mock_result.scalar.return_value = total_embedding_count
    session.exec.return_value = mock_result
    return session


def make_fake_db_row(
    *,
    rank: int = 1,
    score: float = 0.123,
    chunk_id: UUID | None = None,
    parsed_document_id: UUID | None = None,
    document_name: str = "test-doc.pdf",
    sequence_index: int = 1,
    text: str = "这是测试分块文本内容。",
    contextualized_text: str = "上下文增强的测试分块文本。",
    token_count: int = 50,
    heading_path: list[str] | None = None,
    page_numbers: list[int] | None = None,
):
    """Create a fake DB row matching the pgvector JOIN query shape."""
    chunk_id = chunk_id or uuid4()
    parsed_doc_id = parsed_document_id or uuid4()

    embedding = SimpleNamespace(
        id=uuid4(),
        chunk_id=chunk_id,
        parsed_document_id=parsed_doc_id,
        sequence_index=sequence_index,
        model="test-embed-model",
        dimensions=2560,
    )
    chunk = SimpleNamespace(
        id=chunk_id,
        parsed_document_id=parsed_doc_id,
        sequence_index=sequence_index,
        text=text,
        contextualized_text=contextualized_text,
        token_count=token_count,
        heading_path=heading_path or ["第一章", "第一节"],
        page_numbers=page_numbers or [1, 2],
    )
    parsed_doc = SimpleNamespace(id=parsed_doc_id)

    return SimpleNamespace(
        DocumentEmbedding=embedding,
        DocumentChunk=chunk,
        ParsedDocument=parsed_doc,
        document_name=document_name,
        score=score,
    )


# ── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def db_session() -> Generator[Session]:
    """Provide a real SQLite session for the dependency override."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as test_session:
        yield test_session


@pytest.fixture
def search_client(
    db_session: Session,
    request: pytest.FixtureRequest,
) -> Generator[TestClient]:
    """Create a TestClient with all search dependencies overridden.

    Individual tests set markers on the param to configure the overrides.
    """
    overrides = {}

    # Default mocks — tests override as needed via indirect parametrization
    _embedding_adapter = make_fake_embedding_adapter()
    _chat_adapter = make_fake_chat_adapter()
    _chat_config = make_fake_chat_config()
    _session = make_fake_session(
        total_embedding_count=1,
        rows=[make_fake_db_row(rank=1, score=0.10)],
    )

    def _get_session():
        return _session

    def _get_chat_config():
        return _chat_config

    def _get_embedding_adapter():
        return _embedding_adapter

    def _get_chat_adapter():
        return _chat_adapter

    def _get_search_response_cache():
        # 测试默认禁用 L1 搜索响应缓存，避免缓存副作用
        return None

    def _get_search_audit_trail():
        audit_module = import_module("app.services.audit_trail")
        return audit_module.AuditTrail()

    # Import the route's dependency functions (will fail in red phase)
    try:
        search_routes = import_module("app.api.routes.search")
        overrides[search_routes.get_chat_config] = _get_chat_config
        overrides[search_routes.get_embedding_adapter] = _get_embedding_adapter
        overrides[search_routes.get_chat_adapter] = _get_chat_adapter
        overrides[search_routes.get_search_response_cache] = _get_search_response_cache
        overrides[search_routes.get_search_audit_trail] = _get_search_audit_trail
    except ImportError:
        pass  # Red phase — route doesn't exist yet

    overrides[get_session] = _get_session

    # Store refs so tests can configure
    app._search_test_refs = SimpleNamespace(
        session=_session,
        embedding_adapter=_embedding_adapter,
        chat_adapter=_chat_adapter,
        chat_config=_chat_config,
        overrides=overrides,
    )

    for dep, fn in overrides.items():
        app.dependency_overrides[dep] = fn

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
    if hasattr(app, "_search_test_refs"):
        delattr(app, "_search_test_refs")


# ── 1. 正常搜索+生成 → 200 ──────────────────────────────────────────────


# 正常路径：chat 已配置，向量数据存在 → 返回 200 SearchResponse，
# 包含 answer、results、token 统计等完整字段。
def test_search_returns_200_with_answer_and_results(search_client: TestClient):
    response = search_client.post(
        "/api/search",
        json={"query": "测试查询", "top_k": 5},
    )

    assert response.status_code == 200
    payload = response.json()

    # Response metadata
    assert payload["query"] == "测试查询"
    assert payload["top_k"] == 5
    assert len(payload["query_embedding_preview"]) == 5
    assert payload["embedding_dimensions"] == 2560
    assert payload["search_time_ms"] >= 0

    # Results
    assert len(payload["results"]) >= 1
    result = payload["results"][0]
    assert result["rank"] == 1
    assert result["score"] > 0
    assert len(result["text"]) > 0
    assert result["document_name"] == "test-doc.pdf"

    # Answer (LLM generated)
    assert len(payload["answer"]) > 0
    assert payload["answer_tokens"] is not None
    assert payload["answer_tokens"]["total_tokens"] > 0
    assert payload["chat_model"] is not None

    # Prompt transparency
    assert len(payload["prompt_messages"]) > 0

    # Normal path: no generation error
    assert payload["generation_error"] is None


# ── 2. 无向量数据 → 404 ─────────────────────────────────────────────────


# 当 document_embeddings 表为空时，返回 404，告知用户系统中没有可搜索的向量数据。
# 关键约束：
# 1. 不调用 LLM（因为没有上下文可供推理）
# 2. 使用硬编码友好提示，而非 LLM 生成内容
def test_search_returns_404_when_no_vector_data(search_client: TestClient):
    # Arrange — simulate empty DB
    search_client.app._search_test_refs.session.exec.return_value.scalar.return_value = 0
    search_client.app._search_test_refs.session.exec.return_value.all.return_value = []

    response = search_client.post(
        "/api/search",
        json={"query": "任意查询", "top_k": 5},
    )

    assert response.status_code == 404
    detail = response.json()
    assert "detail" in detail
    # 验证硬编码友好提示（非 LLM 生成）
    assert "知识库中暂无任何已向量化的文档" in detail["detail"]
    # 验证 LLM 未被调用 —— 无向量数据时不应产生任何 API 费用
    search_client.app._search_test_refs.chat_adapter.generate.assert_not_called()


# ── 3. 参数校验失败 → 422 ───────────────────────────────────────────────


# query 为空时，Pydantic 验证应返回 422，detail 包含具体字段和约束信息。
def test_search_returns_422_when_query_empty(search_client: TestClient):
    response = search_client.post(
        "/api/search",
        json={"query": "", "top_k": 5},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    # FastAPI 422 detail 为数组，每个元素包含 loc、msg、type
    assert isinstance(detail, list)
    assert any(
        "query" in err.get("loc", []) and "at least 1" in err.get("msg", "").lower()
        for err in detail
    ), f"Expected query min_length validation error, got: {detail}"


# query 长度超过 2000 字符时，应返回 422，detail 指明字段和约束。
def test_search_returns_422_when_query_too_long(search_client: TestClient):
    response = search_client.post(
        "/api/search",
        json={"query": "x" * 2001, "top_k": 5},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert any(
        "query" in err.get("loc", [])
        and (
            "at most 2000" in err.get("msg", "").lower() or "too long" in err.get("msg", "").lower()
        )
        for err in detail
    ), f"Expected query max_length validation error, got: {detail}"


# top_k 小于 1 时，应返回 422，detail 指明字段和约束。
def test_search_returns_422_when_top_k_too_small(search_client: TestClient):
    response = search_client.post(
        "/api/search",
        json={"query": "测试", "top_k": 0},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert any(
        "top_k" in err.get("loc", []) and "greater than or equal to 1" in err.get("msg", "").lower()
        for err in detail
    ), f"Expected top_k ge validation error, got: {detail}"


# top_k 大于 50 时，应返回 422，detail 指明字段和约束。
def test_search_returns_422_when_top_k_too_large(search_client: TestClient):
    response = search_client.post(
        "/api/search",
        json={"query": "测试", "top_k": 51},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert any(
        "top_k" in err.get("loc", []) and "less than or equal to 50" in err.get("msg", "").lower()
        for err in detail
    ), f"Expected top_k le validation error, got: {detail}"


# ── 4. 嵌入失败 → 502 ──────────────────────────────────────────────────


# 当 EmbeddingAdapter.embed_single() 抛出 EmbeddingAPIError 时，
# 路由应捕获并返回 502 Bad Gateway，携带具体错误信息。
def test_search_returns_502_when_embedding_fails(search_client: TestClient):
    embedding_module = import_module("app.services.embedding_adapter")
    search_client.app._search_test_refs.embedding_adapter.embed_single.side_effect = (
        embedding_module.EmbeddingAPIError("Embedding API timeout")
    )

    response = search_client.post(
        "/api/search",
        json={"query": "测试查询", "top_k": 5},
    )

    assert response.status_code == 502
    detail = response.json()
    assert "detail" in detail
    assert "Failed to embed query" in detail["detail"]


# ── 5. chat 禁用 → 503 ──────────────────────────────────────────────────


# 当 chat_model 为空字符串（Chat 功能未配置）时，路由应返回 503，
# 并携带具体的中文错误信息。检索相关的搜索不应执行。
def test_search_returns_503_when_chat_disabled(search_client: TestClient):
    search_client.app._search_test_refs.chat_config = make_fake_chat_config(model="")

    # Re-register the override with the disabled config
    search_routes = import_module("app.api.routes.search")
    app.dependency_overrides[search_routes.get_chat_config] = lambda: make_fake_chat_config(
        model=""
    )

    response = search_client.post(
        "/api/search",
        json={"query": "测试查询", "top_k": 5},
    )

    assert response.status_code == 503
    detail = response.json()
    assert "detail" in detail
    assert "AI 回答生成功能未启用" in detail["detail"]
