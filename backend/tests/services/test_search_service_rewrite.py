# =========================================================================
# 本文件验证 SearchService 与 QueryRewriter 的集成行为。
# 覆盖正常集成（改写查询用于向量化 + rewrite_info 返回）、
# 重写未启用时 rewrite_info=null、重写失败时降级（搜索正常完成）、
# 耗时统计分离（search_time_ms 含重写耗时，rewrite_time_ms 独立记录）。
#
# TDD 红阶段：SearchService 尚未集成 QueryRewriter，测试预期失败。
# =========================================================================

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

# ── helpers ──────────────────────────────────────────────────────────────


def get_search_module():
    """Import the search service module."""
    return import_module("app.services.search")


def get_schema_module():
    """Import the search schemas module."""
    return import_module("app.schemas.search")


def get_rewrite_schema_module():
    """Import RewriteInfo / RewrittenQuery from schemas."""
    return import_module("app.schemas.search")


def make_fake_embedding_adapter(*, vector_dims: int = 2560, model: str = "test-embed-model"):
    """Create a fake EmbeddingAdapter whose ``embed_single`` returns a canned vector."""

    class FakeEmbeddingResult:
        pass

    adapter = MagicMock()
    adapter.config = SimpleNamespace(model=model, dimensions=vector_dims)
    result = FakeEmbeddingResult()
    result.embedding = [0.1] * vector_dims
    adapter.embed_single = MagicMock(return_value=result)
    return adapter


def make_fake_chat_adapter(
    *,
    content: str = "根据文档内容，答案如下。",
    model: str = "test-chat-model",
):
    """Create a fake ChatAdapter whose ``generate`` returns a canned ChatResult."""
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
    """Build a fake ChatConfig with sensible test defaults."""
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


def make_fake_db_row(
    *,
    rank: int = 1,
    score: float = 0.123,
    chunk_id: uuid4 | None = None,
    parsed_document_id: uuid4 | None = None,
    document_name: str = "test-doc.pdf",
    sequence_index: int = 1,
    text: str = "这是测试分块文本内容。",
    contextualized_text: str = "上下文增强的测试分块文本。",
    token_count: int = 50,
    heading_path: list[str] | None = None,
    page_numbers: list[int] | None = None,
    dimensions: int = 2560,
    model: str = "test-embed-model",
):
    """Create a fake DB row as returned by a pgvector cosine-distance JOIN query."""
    chunk_id = chunk_id or uuid4()
    parsed_doc_id = parsed_document_id or uuid4()

    embedding = SimpleNamespace(
        id=uuid4(),
        chunk_id=chunk_id,
        parsed_document_id=parsed_doc_id,
        sequence_index=sequence_index,
        model=model,
        dimensions=dimensions,
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


def make_fake_session(rows: list | None = None, total_count: int | None = None):
    """Create a fake SQLModel Session."""
    session = MagicMock()
    if rows is None:
        rows = []
    if total_count is None:
        total_count = len(rows)

    mock_result = MagicMock()
    mock_result.all.return_value = rows
    mock_result.scalar.return_value = total_count
    mock_result.first.return_value = total_count
    session.exec.return_value = mock_result
    return session


def make_fake_rewriter(
    *,
    original_query: str | None = None,
    rewritten_query: str = "改写后的查询",
    strategy: str = "normalize",
    strategies_used: list[str] | None = None,
    rewrite_time_ms: float = 45.2,
    cache_hit: bool = False,
    rewrite_model: str | None = None,
):
    """Create a synchronous mock QueryRewriter.

    Returns a MagicMock whose ``rewrite`` is a synchronous callable (not a coroutine).
    Tests can override return values or raise exceptions as needed.
    """
    query_rewriter_module = import_module("app.services.query_rewriter")

    rewriter = MagicMock()

    # Build a RewriteResult-like object
    result = query_rewriter_module.RewriteResult(
        original_query=original_query or "原始查询",
        rewritten_queries=[{"query": rewritten_query, "strategy": strategy}],
        strategies_used=strategies_used or [strategy],
        rewrite_time_ms=rewrite_time_ms,
        cache_hit=cache_hit,
        rewrite_model=rewrite_model,
    )

    # Make rewrite a synchronous callable (SearchService will handle sync/async bridge)
    rewriter.rewrite = MagicMock(return_value=result)
    return rewriter


# ── 1. 正常集成：SearchService + QueryRewriter ──────────────────────────


# SearchService.search() 应在查询向量化之前调用 QueryRewriter.rewrite()，
# 使用改写后的首个查询进行向量化，并在 SearchResponse 中返回完整的 rewrite_info。
def test_search_calls_rewriter_and_uses_rewritten_query():
    module = get_search_module()
    schema_module = get_schema_module()

    rows = [make_fake_db_row(rank=1, score=0.10)]
    session = make_fake_session(rows=rows, total_count=1)
    embedding_adapter = make_fake_embedding_adapter()
    chat_adapter = make_fake_chat_adapter()
    chat_config = make_fake_chat_config()

    fake_rewriter = make_fake_rewriter(
        original_query="Python 怎么用",
        rewritten_query="Python 如何使用",
        strategy="normalize",
        rewrite_time_ms=32.5,
    )

    # 使用 query_rewriter 参数构造 SearchService
    service = module.SearchService(
        session=session,
        embedding_adapter=embedding_adapter,
        chat_adapter=chat_adapter,
        chat_config=chat_config,
        query_rewriter=fake_rewriter,
    )

    response = service.search(query="Python 怎么用", top_k=5)

    # ── 验证 QueryRewriter.rewrite() 被调用 ──
    fake_rewriter.rewrite.assert_called_once_with("Python 怎么用", session_id="__default__", history=None)

    # ── 验证向量化使用了改写后的查询 ──
    embedding_adapter.embed_single.assert_called_once()
    embed_call_arg = embedding_adapter.embed_single.call_args[0][0]
    assert embed_call_arg == "Python 如何使用", (
        f"Expected embedding to use rewritten query 'Python 如何使用', got '{embed_call_arg}'"
    )

    # ── 验证 SearchResponse 包含 rewrite_info ──
    assert isinstance(response, schema_module.SearchResponse)
    assert response.rewrite_info is not None
    assert response.rewrite_info.original_query == "Python 怎么用"
    assert len(response.rewrite_info.rewritten_queries) == 1
    assert response.rewrite_info.rewritten_queries[0].query == "Python 如何使用"
    assert response.rewrite_info.rewritten_queries[0].strategy == "normalize"
    assert response.rewrite_info.strategies_used == ["normalize"]
    assert response.rewrite_info.rewrite_time_ms == 32.5
    assert response.rewrite_info.cache_hit is False

    # ── 搜索本身正常完成 ──
    assert response.query == "Python 怎么用"  # 原始查询回显
    assert len(response.results) == 1
    assert response.answer is not None


# 当 RewriteResult 包含多条改写结果时，应全部传递到 rewrite_info，
# 且向量化使用第一条改写结果。
def test_search_uses_first_rewritten_query_when_multiple_rewrites():
    module = get_search_module()

    rows = [make_fake_db_row(rank=1, score=0.10)]
    session = make_fake_session(rows=rows, total_count=1)
    embedding_adapter = make_fake_embedding_adapter()
    chat_adapter = make_fake_chat_adapter()
    chat_config = make_fake_chat_config()

    query_rewriter_module = import_module("app.services.query_rewriter")
    multi_result = query_rewriter_module.RewriteResult(
        original_query="大模型应用",
        rewritten_queries=[
            {"query": "大语言模型应用场景", "strategy": "expand"},
            {"query": "LLM 应用", "strategy": "term_align"},
            {"query": "大模型的应用有哪些", "strategy": "normalize"},
        ],
        strategies_used=["expand", "term_align", "normalize"],
        rewrite_time_ms=78.9,
        cache_hit=False,
    )

    fake_rewriter = MagicMock()
    fake_rewriter.rewrite = MagicMock(return_value=multi_result)

    service = module.SearchService(
        session=session,
        embedding_adapter=embedding_adapter,
        chat_adapter=chat_adapter,
        chat_config=chat_config,
        query_rewriter=fake_rewriter,
    )

    response = service.search(query="大模型应用", top_k=5)

    # 向量化应使用第一条改写结果
    embed_call_arg = embedding_adapter.embed_single.call_args[0][0]
    assert embed_call_arg == "大语言模型应用场景", (
        f"Expected first rewritten query for embedding, got '{embed_call_arg}'"
    )

    # rewrite_info 应包含全部改写结果
    assert response.rewrite_info is not None
    assert len(response.rewrite_info.rewritten_queries) == 3
    assert response.rewrite_info.rewritten_queries[0].query == "大语言模型应用场景"
    assert response.rewrite_info.rewritten_queries[0].strategy == "expand"
    assert response.rewrite_info.rewritten_queries[1].query == "LLM 应用"
    assert response.rewrite_info.rewritten_queries[1].strategy == "term_align"
    assert response.rewrite_info.rewritten_queries[2].query == "大模型的应用有哪些"
    assert response.rewrite_info.rewritten_queries[2].strategy == "normalize"

    assert response.rewrite_info.strategies_used == ["expand", "term_align", "normalize"]
    assert response.rewrite_info.rewrite_time_ms == 78.9


# ── 2. 重写未启用时 rewrite_info 包含基本信息 ─────────────────────────


# 当未传入 query_rewriter 参数（None）时，SearchService 应正常搜索，
# 并返回包含原始查询的基本 RewriteInfo（rewritten_queries 为空）。
def test_search_rewrite_info_has_original_query_when_no_rewriter_provided():
    module = get_search_module()
    schema_module = get_schema_module()

    rows = [make_fake_db_row(rank=1, score=0.10)]
    session = make_fake_session(rows=rows, total_count=1)
    embedding_adapter = make_fake_embedding_adapter()
    chat_adapter = make_fake_chat_adapter()
    chat_config = make_fake_chat_config()

    # query_rewriter 默认为 None（不传入）
    service = module.SearchService(
        session=session,
        embedding_adapter=embedding_adapter,
        chat_adapter=chat_adapter,
        chat_config=chat_config,
    )

    response = service.search(query="测试查询", top_k=5)

    # rewrite_info 应始终非 None，包含原始查询和空改写列表
    assert response.rewrite_info is not None
    assert response.rewrite_info.original_query == "测试查询"
    assert response.rewrite_info.rewritten_queries == []
    assert response.rewrite_info.strategies_used == []
    assert response.rewrite_info.rewrite_time_ms == 0.0
    assert response.rewrite_info.cache_hit is False

    # 向量化应使用原始查询
    embedding_adapter.embed_single.assert_called_once_with("测试查询")

    # 搜索应正常完成
    assert isinstance(response, schema_module.SearchResponse)
    assert len(response.results) == 1


# 当 query_rewriter 被显式传入 None 时，rewrite_info 也包含原始查询信息。
def test_search_rewrite_info_has_original_query_when_rewriter_explicitly_none():
    module = get_search_module()

    rows = [make_fake_db_row(rank=1, score=0.10)]
    session = make_fake_session(rows=rows, total_count=1)
    embedding_adapter = make_fake_embedding_adapter()
    chat_adapter = make_fake_chat_adapter()
    chat_config = make_fake_chat_config()

    service = module.SearchService(
        session=session,
        embedding_adapter=embedding_adapter,
        chat_adapter=chat_adapter,
        chat_config=chat_config,
        query_rewriter=None,
    )

    response = service.search(query="任意查询", top_k=5)

    assert response.rewrite_info is not None
    assert response.rewrite_info.original_query == "任意查询"
    assert response.rewrite_info.rewritten_queries == []
    # 向量化应使用原始查询
    embedding_adapter.embed_single.assert_called_once_with("任意查询")


# ── 3. 重写失败时降级 ──────────────────────────────────────────────────


# 当 QueryRewriter.rewrite() 抛出异常时，SearchService 应捕获异常，
# rewrite_info 包含 error 字段（而非 None），但使用原始查询继续检索，搜索正常完成。
def test_search_graceful_degradation_on_rewrite_failure():
    module = get_search_module()
    schema_module = get_schema_module()

    rows = [make_fake_db_row(rank=1, score=0.10, text="测试内容")]
    session = make_fake_session(rows=rows, total_count=1)
    embedding_adapter = make_fake_embedding_adapter()
    chat_adapter = make_fake_chat_adapter()
    chat_config = make_fake_chat_config()

    fake_rewriter = MagicMock()
    fake_rewriter.rewrite = MagicMock(side_effect=RuntimeError("Query rewriter timeout"))

    service = module.SearchService(
        session=session,
        embedding_adapter=embedding_adapter,
        chat_adapter=chat_adapter,
        chat_config=chat_config,
        query_rewriter=fake_rewriter,
    )

    # 不应抛出异常
    response = service.search(query="重要查询", top_k=5)

    # rewrite_info 应包含 error 字段（区分"未配置"和"配置但失败"）
    assert response.rewrite_info is not None
    assert response.rewrite_info.error is not None
    assert "Query rewriter timeout" in response.rewrite_info.error
    assert response.rewrite_info.original_query == "重要查询"
    assert response.rewrite_info.rewritten_queries == []
    assert response.rewrite_info.strategies_used == []
    assert response.rewrite_info.cache_hit is False

    # 搜索应正常完成 —— 使用原始查询向量化
    assert isinstance(response, schema_module.SearchResponse)
    assert len(response.results) == 1
    assert response.answer is not None

    # 向量化回退到原始查询
    embedding_adapter.embed_single.assert_called_once_with("重要查询")


# 重写失败时 SearchResponse 中 generation_error 应仅为 chat 相关错误
# （不应包含重写失败信息，重写失败属于静默降级，不影响搜索主流程）。
# 但 rewrite_info.error 应记录重写失败原因，便于调试。
def test_search_rewrite_failure_does_not_affect_generation_error():
    module = get_search_module()

    rows = [make_fake_db_row(rank=1, score=0.10, text="有效内容")]
    session = make_fake_session(rows=rows, total_count=1)
    embedding_adapter = make_fake_embedding_adapter()
    chat_adapter = make_fake_chat_adapter(content="正常回答")
    chat_config = make_fake_chat_config()

    fake_rewriter = MagicMock()
    fake_rewriter.rewrite = MagicMock(side_effect=RuntimeError("Rewriter error"))

    service = module.SearchService(
        session=session,
        embedding_adapter=embedding_adapter,
        chat_adapter=chat_adapter,
        chat_config=chat_config,
        query_rewriter=fake_rewriter,
    )

    response = service.search(query="测试查询", top_k=5)

    # 重写失败不影响 LLM 生成的正常完成
    assert response.generation_error is None
    assert response.answer == "正常回答"

    # rewrite_info 保留失败信息（error 字段），但 generation_error 不变
    assert response.rewrite_info is not None
    assert response.rewrite_info.error is not None
    assert "Rewriter error" in response.rewrite_info.error


# 当重写成功但后续向量化或 LLM 调用失败时，rewrite_info 应仍然保留。
# 这确保了即使下游失败，重写信息对调试仍然可见。
def test_search_preserves_rewrite_info_when_llm_fails():
    module = get_search_module()
    chat_module = import_module("app.services.chat_adapter")

    rows = [make_fake_db_row(rank=1, score=0.10, text="测试文本")]
    session = make_fake_session(rows=rows, total_count=1)
    embedding_adapter = make_fake_embedding_adapter()
    chat_adapter = make_fake_chat_adapter()
    # LLM 调用失败
    chat_adapter.generate.side_effect = chat_module.ChatAPIError("LLM timeout", status_code=502)
    chat_config = make_fake_chat_config()

    fake_rewriter = make_fake_rewriter(
        original_query="上游查询",
        rewritten_query="改写版本",
        strategy="normalize",
    )

    service = module.SearchService(
        session=session,
        embedding_adapter=embedding_adapter,
        chat_adapter=chat_adapter,
        chat_config=chat_config,
        query_rewriter=fake_rewriter,
    )

    response = service.search(query="上游查询", top_k=5)

    # rewrite_info 应保留（重写成功发生在 LLM 失败之前）
    assert response.rewrite_info is not None
    assert response.rewrite_info.original_query == "上游查询"
    assert response.rewrite_info.rewritten_queries[0].query == "改写版本"

    # LLM 失败已优雅降级
    assert response.generation_error is not None
    assert "LLM timeout" in response.generation_error


# ── 4. 耗时统计分离 ────────────────────────────────────────────────────


# search_time_ms 应包含重写耗时（因为重写是搜索管线的一部分），
# 而 rewrite_time_ms 应独立记录重写自身的耗时。
def test_search_time_includes_rewrite_time_and_rewrite_time_independent():
    module = get_search_module()

    rows = [make_fake_db_row(rank=1, score=0.10)]
    session = make_fake_session(rows=rows, total_count=1)
    embedding_adapter = make_fake_embedding_adapter()
    chat_adapter = make_fake_chat_adapter()
    chat_config = make_fake_chat_config()

    # 模拟重写耗时（使用远小于实际搜索耗时的值，因为 mock 瞬时返回，
    # 但 RewriteResult 携带的是"模拟的内部测量耗时"）
    fake_rewriter = make_fake_rewriter(
        original_query="查询",
        rewritten_query="改写查询",
        rewrite_time_ms=0.5,  # 模拟内部测量的耗时，远小于实际搜索耗时
    )

    service = module.SearchService(
        session=session,
        embedding_adapter=embedding_adapter,
        chat_adapter=chat_adapter,
        chat_config=chat_config,
        query_rewriter=fake_rewriter,
    )

    response = service.search(query="查询", top_k=5)

    # rewrite_time_ms 应独立记录重写耗时
    assert response.rewrite_info is not None
    assert response.rewrite_info.rewrite_time_ms == 0.5

    # search_time_ms 应 >= rewrite_time_ms（因为搜索包含重写 + 向量化 + 检索 + LLM）
    assert response.search_time_ms >= response.rewrite_info.rewrite_time_ms, (
        f"search_time_ms ({response.search_time_ms:.2f}) should be >= "
        f"rewrite_time_ms ({response.rewrite_info.rewrite_time_ms:.2f})"
    )


# search_time_ms 和 rewrite_time_ms 均应为 >= 0 的浮点数。
def test_timing_fields_are_non_negative():
    module = get_search_module()

    rows = [make_fake_db_row(rank=1, score=0.10)]
    session = make_fake_session(rows=rows, total_count=1)
    embedding_adapter = make_fake_embedding_adapter()
    chat_adapter = make_fake_chat_adapter()
    chat_config = make_fake_chat_config()

    fake_rewriter = make_fake_rewriter()

    service = module.SearchService(
        session=session,
        embedding_adapter=embedding_adapter,
        chat_adapter=chat_adapter,
        chat_config=chat_config,
        query_rewriter=fake_rewriter,
    )

    response = service.search(query="测试", top_k=5)

    assert response.search_time_ms >= 0
    assert response.rewrite_info is not None
    assert response.rewrite_info.rewrite_time_ms >= 0


# ── 5. 缓存命中场景 ────────────────────────────────────────────────────


# 当 QueryRewriter 返回 cache_hit=True 时，rewrite_info 应反映缓存命中状态。
def test_rewrite_info_reflects_cache_hit():
    module = get_search_module()

    rows = [make_fake_db_row(rank=1, score=0.10)]
    session = make_fake_session(rows=rows, total_count=1)
    embedding_adapter = make_fake_embedding_adapter()
    chat_adapter = make_fake_chat_adapter()
    chat_config = make_fake_chat_config()

    fake_rewriter = make_fake_rewriter(
        original_query="经常查询的问题",
        rewritten_query="经常查询的问题（缓存命中）",
        strategy="direct",
        cache_hit=True,
        rewrite_time_ms=0.5,  # 缓存命中时耗时很低
    )

    service = module.SearchService(
        session=session,
        embedding_adapter=embedding_adapter,
        chat_adapter=chat_adapter,
        chat_config=chat_config,
        query_rewriter=fake_rewriter,
    )

    response = service.search(query="经常查询的问题", top_k=5)

    assert response.rewrite_info is not None
    assert response.rewrite_info.cache_hit is True
    assert response.rewrite_info.rewrite_time_ms == 0.5


# ── 6. 对话历史传递 ────────────────────────────────────────────────────


# SearchService 可能接收对话历史并传递给 QueryRewriter，
# 用于上下文融合（指代词消解）。当前 SearchRequest 不含 history 字段，
# 但 SearchService.search() 应能可选接收 history 参数。
def test_search_passes_history_to_rewriter():
    module = get_search_module()

    rows = [make_fake_db_row(rank=1, score=0.10)]
    session = make_fake_session(rows=rows, total_count=1)
    embedding_adapter = make_fake_embedding_adapter()
    chat_adapter = make_fake_chat_adapter()
    chat_config = make_fake_chat_config()

    fake_rewriter = make_fake_rewriter(
        original_query="它怎么用",
        rewritten_query="Python 怎么使用",
        strategy="context_fusion",
    )

    service = module.SearchService(
        session=session,
        embedding_adapter=embedding_adapter,
        chat_adapter=chat_adapter,
        chat_config=chat_config,
        query_rewriter=fake_rewriter,
    )

    history = [{"role": "user", "content": "什么是 Python？"}]

    response = service.search(query="它怎么用", top_k=5, history=history)

    # 验证 history 被传递给 rewriter（session_id 由 SearchService 从 history 派生）
    fake_rewriter.rewrite.assert_called_once_with("它怎么用", session_id="f22eb635d9725bf2", history=history)

    # rewrite_info 应反映上下文融合策略
    assert response.rewrite_info is not None
    assert response.rewrite_info.strategies_used == ["context_fusion"]


# 当不传入 history 时，rewrite() 的 history 参数应为 None。
def test_search_passes_none_history_when_not_provided():
    module = get_search_module()

    rows = [make_fake_db_row(rank=1, score=0.10)]
    session = make_fake_session(rows=rows, total_count=1)
    embedding_adapter = make_fake_embedding_adapter()
    chat_adapter = make_fake_chat_adapter()
    chat_config = make_fake_chat_config()

    fake_rewriter = make_fake_rewriter()

    service = module.SearchService(
        session=session,
        embedding_adapter=embedding_adapter,
        chat_adapter=chat_adapter,
        chat_config=chat_config,
        query_rewriter=fake_rewriter,
    )

    service.search(query="独立查询", top_k=5)

    fake_rewriter.rewrite.assert_called_once_with("独立查询", session_id="__default__", history=None)
