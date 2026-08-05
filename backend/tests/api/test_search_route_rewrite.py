# =========================================================================
# 本文件验证 POST /api/search 端点与 QueryRewriter 的端到端集成。
# 覆盖含 rewrite_info 的完整响应 JSON 序列化验证、rewrite_info=null
# 时 JSON 不包含该字段或为 null。
#
# TDD 红阶段：路由尚未注入 QueryRewriter，测试预期失败。
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
    """Create a fake EmbeddingAdapter."""
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
    """Create a fake SQLModel Session for the search query."""
    session = MagicMock()
    if rows is None:
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


def make_fake_rewriter_response(
    original_query: str = "测试查询",
    rewritten_query: str = "改写后的测试查询",
    strategy: str = "normalize",
    strategies_used: list[str] | None = None,
    rewrite_time_ms: float = 42.0,
    cache_hit: bool = False,
    rewrite_model: str | None = None,
):
    """Build a RewriteResult-like object for mock QueryRewriter."""
    query_rewriter_module = import_module("app.services.query_rewriter")
    return query_rewriter_module.RewriteResult(
        original_query=original_query,
        rewritten_queries=[{"query": rewritten_query, "strategy": strategy}],
        strategies_used=strategies_used if strategies_used is not None else [strategy],
        rewrite_time_ms=rewrite_time_ms,
        cache_hit=cache_hit,
        rewrite_model=rewrite_model,
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
) -> Generator[TestClient]:
    """Create a TestClient with search dependencies overridden.

    Tests configure the mock rewriter and other overrides via
    ``app._search_test_refs`` after the fixture yields.
    """
    _embedding_adapter = make_fake_embedding_adapter()
    _chat_adapter = make_fake_chat_adapter()
    _chat_config = make_fake_chat_config()
    _session = make_fake_session(
        total_embedding_count=1,
        rows=[make_fake_db_row(rank=1, score=0.10)],
    )

    # Mock QueryRewriter — defaults to returning a successful rewrite
    _query_rewriter = MagicMock()
    _query_rewriter.rewrite = MagicMock(return_value=make_fake_rewriter_response())

    def _get_session():
        return _session

    def _get_chat_config():
        return _chat_config

    def _get_embedding_adapter():
        return _embedding_adapter

    def _get_chat_adapter():
        return _chat_adapter

    def _get_query_rewriter():
        return _query_rewriter

    def _get_search_response_cache():
        # 测试默认禁用 L1 搜索响应缓存
        return None

    def _get_search_audit_trail():
        audit_module = import_module("app.services.audit_trail")
        return audit_module.AuditTrail()

    # Import the route's dependency functions
    try:
        search_routes = import_module("app.api.routes.search")
        overrides = {
            search_routes.get_chat_config: _get_chat_config,
            search_routes.get_embedding_adapter: _get_embedding_adapter,
            search_routes.get_chat_adapter: _get_chat_adapter,
            search_routes.get_search_response_cache: _get_search_response_cache,
            search_routes.get_search_audit_trail: _get_search_audit_trail,
        }
        # 如果路由已有 get_query_rewriter，则覆盖；否则仅存储引用
        if hasattr(search_routes, "get_query_rewriter"):
            overrides[search_routes.get_query_rewriter] = _get_query_rewriter
    except ImportError:
        overrides = {}

    overrides[get_session] = _get_session

    # Store refs so tests can configure
    app._search_test_refs = SimpleNamespace(
        session=_session,
        embedding_adapter=_embedding_adapter,
        chat_adapter=_chat_adapter,
        chat_config=_chat_config,
        query_rewriter=_query_rewriter,
        overrides=overrides,
    )

    for dep, fn in overrides.items():
        app.dependency_overrides[dep] = fn

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
    if hasattr(app, "_search_test_refs"):
        delattr(app, "_search_test_refs")


# ── 1. 含 rewrite_info 的完整响应 JSON 序列化 ──────────────────────────


# POST /api/search 的响应 JSON 应包含完整的 rewrite_info 对象：
# original_query、rewritten_queries（数组，每项含 query 和 strategy）、
# strategies_used、rewrite_time_ms、cache_hit。
def test_search_response_includes_rewrite_info_in_json(search_client: TestClient):
    # Configure mock rewriter to return specific data
    rewriter = search_client.app._search_test_refs.query_rewriter
    rewriter.rewrite.return_value = make_fake_rewriter_response(
        original_query="Python 怎么用",
        rewritten_query="Python 如何使用",
        strategy="normalize",
        strategies_used=["normalize"],
        rewrite_time_ms=35.7,
        cache_hit=False,
    )

    response = search_client.post(
        "/api/search",
        json={"query": "Python 怎么用", "top_k": 5},
    )

    assert response.status_code == 200
    payload = response.json()

    # rewrite_info 应存在且不为 null
    assert "rewrite_info" in payload
    assert payload["rewrite_info"] is not None

    ri = payload["rewrite_info"]

    # 字段类型验证
    assert isinstance(ri["original_query"], str)
    assert ri["original_query"] == "Python 怎么用"

    assert isinstance(ri["rewritten_queries"], list)
    assert len(ri["rewritten_queries"]) == 1
    assert isinstance(ri["rewritten_queries"][0], dict)
    assert ri["rewritten_queries"][0]["query"] == "Python 如何使用"
    assert ri["rewritten_queries"][0]["strategy"] == "normalize"

    assert isinstance(ri["strategies_used"], list)
    assert ri["strategies_used"] == ["normalize"]

    assert isinstance(ri["rewrite_time_ms"], (int, float))
    assert ri["rewrite_time_ms"] == 35.7

    assert isinstance(ri["cache_hit"], bool)
    assert ri["cache_hit"] is False


# 多条改写结果时应全部序列化。
def test_search_response_json_multiple_rewrites(search_client: TestClient):
    query_rewriter_module = import_module("app.services.query_rewriter")
    rewriter = search_client.app._search_test_refs.query_rewriter
    rewriter.rewrite.return_value = query_rewriter_module.RewriteResult(
        original_query="大模型应用",
        rewritten_queries=[
            {"query": "大语言模型应用场景", "strategy": "expand"},
            {"query": "LLM 应用", "strategy": "term_align"},
        ],
        strategies_used=["expand", "term_align"],
        rewrite_time_ms=55.0,
        cache_hit=False,
    )

    response = search_client.post(
        "/api/search",
        json={"query": "大模型应用", "top_k": 5},
    )

    assert response.status_code == 200
    payload = response.json()

    ri = payload["rewrite_info"]
    assert len(ri["rewritten_queries"]) == 2
    assert ri["rewritten_queries"][0]["query"] == "大语言模型应用场景"
    assert ri["rewritten_queries"][0]["strategy"] == "expand"
    assert ri["rewritten_queries"][1]["query"] == "LLM 应用"
    assert ri["rewritten_queries"][1]["strategy"] == "term_align"

    assert ri["strategies_used"] == ["expand", "term_align"]
    assert ri["rewrite_time_ms"] == 55.0


# strategy 可为 null（当重写未使用特定策略时，如 direct 透传）。
def test_search_response_json_rewritten_query_strategy_nullable(search_client: TestClient):
    query_rewriter_module = import_module("app.services.query_rewriter")
    rewriter = search_client.app._search_test_refs.query_rewriter
    rewriter.rewrite.return_value = query_rewriter_module.RewriteResult(
        original_query="简单查询",
        rewritten_queries=[{"query": "简单查询", "strategy": None}],
        strategies_used=[],
        rewrite_time_ms=1.0,
        cache_hit=True,
    )

    response = search_client.post(
        "/api/search",
        json={"query": "简单查询", "top_k": 5},
    )

    assert response.status_code == 200
    payload = response.json()

    ri = payload["rewrite_info"]
    # strategy 为 null 时 JSON 中应为 None/null
    assert ri["rewritten_queries"][0]["strategy"] is None
    assert ri["strategies_used"] == []
    assert ri["cache_hit"] is True


# ── 2. rewrite_info 重写未启用时包含基本信息 ──────────────────────────


# 当重写未启用（get_query_rewriter 返回 None）时，JSON 响应中的 rewrite_info
# 应包含原始查询和空改写列表（不再为 null）。
def test_search_response_rewrite_info_not_null_when_no_rewriter(search_client: TestClient):
    # Override get_query_rewriter to return None, simulating disabled rewriter
    search_routes = import_module("app.api.routes.search")
    search_client.app.dependency_overrides[search_routes.get_query_rewriter] = lambda: None

    response = search_client.post(
        "/api/search",
        json={"query": "正常查询", "top_k": 5},
    )

    assert response.status_code == 200
    payload = response.json()

    # rewrite_info 应始终非 null
    assert "rewrite_info" in payload
    assert payload["rewrite_info"] is not None
    ri = payload["rewrite_info"]
    assert ri["original_query"] == "正常查询"
    assert ri["rewritten_queries"] == []
    assert ri["strategies_used"] == []
    assert ri["rewrite_time_ms"] == 0.0
    assert ri["cache_hit"] is False


# rewrite_info 始终非 null 时，其余搜索字段应完整正常返回。
def test_search_response_has_all_fields_when_rewriter_disabled(search_client: TestClient):
    # Override get_query_rewriter to return None
    search_routes = import_module("app.api.routes.search")
    search_client.app.dependency_overrides[search_routes.get_query_rewriter] = lambda: None

    response = search_client.post(
        "/api/search",
        json={"query": "正常查询", "top_k": 5},
    )

    assert response.status_code == 200
    payload = response.json()

    # 搜索相关字段应完整
    assert payload["query"] == "正常查询"
    assert payload["top_k"] == 5
    assert len(payload["query_embedding_preview"]) == 5
    assert payload["embedding_dimensions"] == 2560
    assert payload["search_time_ms"] >= 0
    assert isinstance(payload["results"], list)
    assert len(payload["results"]) >= 1
    assert len(payload["answer"]) > 0
    # rewrite_info 始终非 null
    assert payload["rewrite_info"] is not None
    assert payload["rewrite_info"]["original_query"] == "正常查询"


# ── 3. 重写失败时降级：rewrite_info 包含 error 字段但搜索正常完成 ──────────


# 当 QueryRewriter.rewrite() 抛出异常时，路由应捕获并返回 200，
# rewrite_info 包含 error 字段（非 null），但搜索本身正常完成。
def test_search_returns_200_with_rewrite_info_error_on_rewrite_failure(
    search_client: TestClient,
):
    rewriter = search_client.app._search_test_refs.query_rewriter
    rewriter.rewrite.side_effect = RuntimeError("Query rewriter crash")

    response = search_client.post(
        "/api/search",
        json={"query": "会触发重写错误的查询", "top_k": 5},
    )

    # 应返回 200（重写失败不影响搜索结果）
    assert response.status_code == 200
    payload = response.json()

    # rewrite_info 应包含 error 字段（区分"未配置"和"配置但失败"）
    assert payload["rewrite_info"] is not None
    assert payload["rewrite_info"]["error"] is not None
    assert "Query rewriter crash" in payload["rewrite_info"]["error"]
    assert payload["rewrite_info"]["original_query"] == "会触发重写错误的查询"

    # 搜索结果应正常
    assert len(payload["results"]) >= 1
    assert len(payload["answer"]) > 0
    assert payload["search_time_ms"] >= 0


# ── 4. 缓存命中的 JSON 序列化 ──────────────────────────────────────────


def test_search_response_json_cache_hit_serialization(search_client: TestClient):
    rewriter = search_client.app._search_test_refs.query_rewriter
    rewriter.rewrite.return_value = make_fake_rewriter_response(
        original_query="重复查询",
        rewritten_query="重复查询",
        strategy="direct",
        strategies_used=[],
        rewrite_time_ms=0.8,
        cache_hit=True,
    )

    response = search_client.post(
        "/api/search",
        json={"query": "重复查询", "top_k": 5},
    )

    assert response.status_code == 200
    payload = response.json()

    ri = payload["rewrite_info"]
    assert ri["cache_hit"] is True
    assert ri["rewrite_time_ms"] == 0.8
    assert ri["strategies_used"] == []
