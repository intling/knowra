"""验证 SearchResponse 新增 rewrite_info 字段及其 RewriteInfo/RewrittenQuery 子模型。

TDD 红阶段：测试先写，确保 RewriteInfo / RewrittenQuery / SearchResponse.rewrite_info
的 Pydantic 模型满足契约定义。模型尚未实现时测试失败是预期行为。
"""

import json
from importlib import import_module

import pytest

# ── 模块延迟导入 —— 红阶段某些模型可能尚不存在 ────────────────────────────


def _get_schema_module():
    return import_module("app.schemas.search")


def _get_search_response_cls():
    return _get_schema_module().SearchResponse


def _get_search_request_cls():
    return _get_schema_module().SearchRequest


# ── RewriteInfo / RewrittenQuery 存在性 ──────────────────────────────────


def test_rewrite_info_model_exists():
    """RewriteInfo 模型应在 schemas/search.py 中可导入。"""
    mod = _get_schema_module()
    assert hasattr(mod, "RewriteInfo"), "Missing RewriteInfo in app.schemas.search"


def test_rewritten_query_model_exists():
    """RewrittenQuery 模型应在 schemas/search.py 中可导入。"""
    mod = _get_schema_module()
    assert hasattr(mod, "RewrittenQuery"), "Missing RewrittenQuery in app.schemas.search"


# ── RewrittenQuery 字段 ──────────────────────────────────────────────────


def test_rewritten_query_fields():
    """RewrittenQuery 应包含 query (str) 和 strategy (str | None) 字段。"""
    RewrittenQuery = _get_schema_module().RewrittenQuery

    rq = RewrittenQuery(query="改写后的查询文本", strategy="normalize")
    assert rq.query == "改写后的查询文本"
    assert rq.strategy == "normalize"

    # strategy 为 None 时也应被接受
    rq_no_strat = RewrittenQuery(query="改写后的查询文本", strategy=None)
    assert rq_no_strat.strategy is None


def test_rewritten_query_strategy_optional():
    """strategy 字段应是可选的（可为 None）。"""
    RewrittenQuery = _get_schema_module().RewrittenQuery

    # 不传 strategy 应能成功构造
    rq = RewrittenQuery(query="改写后的查询文本")
    assert rq.strategy is None


# ── RewriteInfo 字段 ─────────────────────────────────────────────────────


def test_rewrite_info_fields():
    """RewriteInfo 应包含 original_query, rewritten_queries, strategies_used,
    rewrite_time_ms, cache_hit, error, rewrite_model 七个字段。"""
    RewriteInfo = _get_schema_module().RewriteInfo
    RewrittenQuery = _get_schema_module().RewrittenQuery

    info = RewriteInfo(
        original_query="它怎么用",
        rewritten_queries=[
            RewrittenQuery(query="Python 怎么使用", strategy="context_fusion"),
            RewrittenQuery(query="Python 如何使用", strategy="normalize"),
        ],
        strategies_used=["context_fusion", "normalize"],
        rewrite_time_ms=45.2,
        cache_hit=False,
    )

    assert info.original_query == "它怎么用"
    assert len(info.rewritten_queries) == 2
    assert info.rewritten_queries[0].query == "Python 怎么使用"
    assert info.rewritten_queries[0].strategy == "context_fusion"
    assert info.strategies_used == ["context_fusion", "normalize"]
    assert info.rewrite_time_ms == 45.2
    assert info.cache_hit is False
    assert info.error is None  # 默认值应为 None


def test_rewrite_info_type_checks():
    """RewriteInfo 字段类型应正确：
    - original_query: str
    - rewritten_queries: list[RewrittenQuery]
    - strategies_used: list[str]
    - rewrite_time_ms: float
    - cache_hit: bool
    - error: str | None
    - rewrite_model: str | None
    """
    RewriteInfo = _get_schema_module().RewriteInfo
    RewrittenQuery = _get_schema_module().RewrittenQuery

    info = RewriteInfo(
        original_query="test",
        rewritten_queries=[],
        strategies_used=[],
        rewrite_time_ms=0.0,
        cache_hit=True,
    )

    assert isinstance(info.original_query, str)
    assert isinstance(info.rewritten_queries, list)
    # 空列表场景也应成立
    assert isinstance(info.strategies_used, list)
    assert isinstance(info.rewrite_time_ms, float)
    assert isinstance(info.cache_hit, bool)
    assert info.error is None
    assert info.rewrite_model is None

    # 带 rewrite_model 的构造
    info_with_model = RewriteInfo(
        original_query="test",
        rewritten_queries=[],
        strategies_used=[],
        rewrite_time_ms=0.0,
        cache_hit=True,
        rewrite_model="qwen3.5-plus",
    )
    assert info_with_model.rewrite_model == "qwen3.5-plus"

    # 带 error 的构造：重写失败场景
    info_with_error = RewriteInfo(
        original_query="失败查询",
        rewritten_queries=[],
        strategies_used=[],
        rewrite_time_ms=12.3,
        cache_hit=False,
        error="Query rewriter timeout",
    )
    assert info_with_error.error == "Query rewriter timeout"
    assert isinstance(info_with_error.error, str)

    # 带数据时的类型验证
    info2 = RewriteInfo(
        original_query="原始查询",
        rewritten_queries=[RewrittenQuery(query="重写查询", strategy=None)],
        strategies_used=["normalize"],
        rewrite_time_ms=12.5,
        cache_hit=False,
    )
    assert isinstance(info2.rewritten_queries[0], RewrittenQuery)


def test_rewrite_info_error_field_nullable():
    """RewriteInfo.error 字段默认为 None，仅在重写失败时设置。"""
    RewriteInfo = _get_schema_module().RewriteInfo

    # 构造时不传 error → 应为 None
    info = RewriteInfo(
        original_query="查询",
        rewritten_queries=[],
        strategies_used=[],
        rewrite_time_ms=0.0,
        cache_hit=True,
    )
    assert info.error is None

    # 显式传 None → 应为 None
    info2 = RewriteInfo(
        original_query="查询",
        rewritten_queries=[],
        strategies_used=[],
        rewrite_time_ms=0.0,
        cache_hit=True,
        error=None,
    )
    assert info2.error is None


# ── SearchResponse 集成 ──────────────────────────────────────────────────


def test_search_response_has_rewrite_info_field():
    """SearchResponse 应新增 rewrite_info: RewriteInfo 字段，默认由 factory 提供。"""
    SearchResponse = _get_search_response_cls()

    # 验证字段存在
    fields = SearchResponse.model_fields
    assert "rewrite_info" in fields, "SearchResponse 缺少 rewrite_info 字段"

    field_info = fields["rewrite_info"]
    assert field_info.default_factory is not None, "rewrite_info 应有 default_factory"


def test_search_response_rewrite_info_null_serialization():
    """rewrite_info 不传时 SearchResponse 应使用默认 factory 创建。"""
    SearchResponse = _get_search_response_cls()

    resp = SearchResponse(
        query="测试查询",
        query_embedding_preview=[0.1, 0.2, 0.3, 0.4, 0.5],
        embedding_model="test-model",
        embedding_dimensions=2560,
        top_k=5,
        total_searched=100,
        searched_document_count=3,
        search_time_ms=45.2,
        results=[],
        answer="答案",
    )

    data = resp.model_dump()
    assert data["rewrite_info"] is not None
    assert data["rewrite_info"]["original_query"] == ""
    # JSON 序列化应成功
    json_str = resp.model_dump_json()
    parsed = json.loads(json_str)
    assert parsed["rewrite_info"] is not None


def test_search_response_rewrite_info_with_complete_data():
    """rewrite_info 包含完整数据时 SearchResponse 应正确序列化所有字段。"""
    SearchResponse = _get_search_response_cls()
    RewriteInfo = _get_schema_module().RewriteInfo
    RewrittenQuery = _get_schema_module().RewrittenQuery

    rewrite_info = RewriteInfo(
        original_query="它怎么用",
        rewritten_queries=[
            RewrittenQuery(query="Python 怎么使用", strategy="context_fusion"),
            RewrittenQuery(query="Python 如何使用", strategy="normalize"),
        ],
        strategies_used=["context_fusion", "normalize"],
        rewrite_time_ms=45.2,
        cache_hit=False,
    )

    resp = SearchResponse(
        query="它怎么用",
        query_embedding_preview=[0.1, 0.2, 0.3, 0.4, 0.5],
        embedding_model="test-model",
        embedding_dimensions=2560,
        top_k=5,
        total_searched=100,
        searched_document_count=3,
        search_time_ms=100.0,
        results=[],
        answer="答案",
        rewrite_info=rewrite_info,
    )

    data = resp.model_dump()
    ri = data["rewrite_info"]

    assert ri["original_query"] == "它怎么用"
    assert len(ri["rewritten_queries"]) == 2
    assert ri["rewritten_queries"][0]["query"] == "Python 怎么使用"
    assert ri["rewritten_queries"][0]["strategy"] == "context_fusion"
    assert ri["rewritten_queries"][1]["strategy"] == "normalize"
    assert ri["strategies_used"] == ["context_fusion", "normalize"]
    assert ri["rewrite_time_ms"] == 45.2
    assert ri["cache_hit"] is False


def test_search_response_rewrite_info_json_roundtrip():
    """SearchResponse 的 JSON 序列化/反序列化往返应保留 rewrite_info 数据。"""
    SearchResponse = _get_search_response_cls()
    RewriteInfo = _get_schema_module().RewriteInfo
    RewrittenQuery = _get_schema_module().RewrittenQuery

    original = SearchResponse(
        query="测试",
        query_embedding_preview=[0.0, 0.0, 0.0, 0.0, 0.0],
        embedding_model="m",
        embedding_dimensions=4,
        top_k=1,
        total_searched=1,
        searched_document_count=1,
        search_time_ms=10.0,
        rewrite_info=RewriteInfo(
            original_query="测试",
            rewritten_queries=[RewrittenQuery(query="改写测试", strategy=None)],
            strategies_used=[],
            rewrite_time_ms=5.0,
            cache_hit=True,
        ),
    )

    json_str = original.model_dump_json()
    parsed = json.loads(json_str)

    # 从 JSON 重新构造
    reconstructed = SearchResponse.model_validate(parsed)
    assert reconstructed.rewrite_info is not None
    assert reconstructed.rewrite_info.original_query == "测试"
    assert reconstructed.rewrite_info.cache_hit is True
    assert len(reconstructed.rewrite_info.rewritten_queries) == 1
    assert reconstructed.rewrite_info.rewritten_queries[0].query == "改写测试"


# ── SearchRequest 不变 ───────────────────────────────────────────────────


def test_search_request_has_no_rewrite_fields():
    """SearchRequest 不包含 rewrite_model 字段 —— 模型由服务端配置决定。"""
    SearchRequest = _get_search_request_cls()

    req = SearchRequest(query="测试查询", top_k=10)
    data = req.model_dump()

    # 确认包含 query、top_k、history、session_id，不包含 rewrite_model
    assert set(data.keys()) == {"query", "top_k", "history", "session_id"}
    assert data["history"] is None
    assert data["session_id"] is None


def test_search_request_unchanged():
    """SearchRequest 行为应与之前基本一致（query 长度限制、top_k 范围等）。"""
    SearchRequest = _get_search_request_cls()

    # 正常构造
    req = SearchRequest(query="正常查询")
    assert req.query == "正常查询"
    assert req.top_k == 5  # 默认值

    # query 不能为空
    with pytest.raises(ValueError):
        SearchRequest(query="")

    # top_k 必须在 1-50 之间
    with pytest.raises(ValueError):
        SearchRequest(query="q", top_k=0)

    with pytest.raises(ValueError):
        SearchRequest(query="q", top_k=51)


def test_search_request_history_optional():
    """SearchRequest.history 为可选字段，默认应为 None。"""
    SearchRequest = _get_search_request_cls()

    # 不传 history
    req = SearchRequest(query="测试")
    assert req.history is None

    # 传入 history
    history = [{"role": "user", "content": "什么是 Python？"}]
    req2 = SearchRequest(query="它怎么用", history=history)
    assert req2.history == history


def test_search_request_history_max_length():
    """SearchRequest.history 不能超过 20 轮。"""
    SearchRequest = _get_search_request_cls()

    # 21 轮应触发验证错误
    long_history = [{"role": "user", "content": f"msg {i}"} for i in range(21)]
    with pytest.raises(ValueError):
        SearchRequest(query="q", history=long_history)
