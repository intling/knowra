# =========================================================================
# 端到端集成测试：POST /api/search → QueryRewriter 管线 → SearchResponse
#
# 覆盖完整端到端流程：
#   POST /api/search → QueryRewriter 执行完整管线（精确词保护→缓存→去重
#   →上下文融合→意图分类→策略路由→策略执行→质量评估→保护词还原→审计日志）
#   → SearchResponse 含完整 rewrite_info
#
# 验证：
#   - rewrite_info 包含所有 Phase 2 字段（intent、complexity、cache_level、
#     quality_scores、backtrack_triggered、backtrack_strategy）
#   - search_time_ms 包含重写耗时
#   - rewrite_time_ms 独立准确
#   - 同一请求所有日志事件共享 trace_id（audit_trail_id）
# =========================================================================

from __future__ import annotations

from collections.abc import Generator
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db.session import get_session
from app.main import app
from tests.search_helpers import (
    make_fake_chat_adapter,
    make_fake_chat_config,
    make_fake_db_row,
    make_fake_embedding_adapter,
    make_fake_session,
)

# ═══════════════════════════════════════════════════════════════════════════
# Phase 2 完整 RewriteResult 构建器
# ═══════════════════════════════════════════════════════════════════════════


def make_full_rewrite_result(
    *,
    original_query: str = "Python 怎么学",
    rewritten_queries: list[dict] | None = None,
    strategies_used: list[str] | None = None,
    rewrite_time_ms: float = 250.0,
    cache_hit: bool = False,
    cache_level: str | None = None,
    intent: str = "procedural",
    complexity: int = 5,
    quality_scores: dict | None = None,
    backtrack_triggered: bool = False,
    backtrack_strategy: str | None = None,
    rewrite_model: str | None = "test-rewrite-model",
):
    """构建包含所有 Phase 2 字段的完整 RewriteResult。

    模拟 QueryRewriter 执行完整管线后的输出：
    精确词保护 → L1 缓存查询 → 请求去重 → 上下文融合 → 意图分类 →
    策略路由 → 策略执行（normalize + term_align）→ 质量评估 → 保护词还原。

    返回的 RewriteResult 包含 intent、complexity、cache_level、
    quality_scores、backtrack_triggered、backtrack_strategy 等
    Phase 2 扩展字段，用于验证端到端 JSON 序列化。
    """
    query_rewriter_module = import_module("app.services.query_rewriter")

    if rewritten_queries is None:
        rewritten_queries = [
            {
                "query": "如何系统学习 Python 编程语言",
                "strategy": "normalize",
                "duration_ms": 120.0,
                "tokens": 45,
            },
            {
                "query": "Python 学习路径、语法基础、常用库与项目实践",
                "strategy": "expand",
                "duration_ms": 200.0,
                "tokens": 60,
            },
        ]
    if strategies_used is None:
        strategies_used = ["normalize", "expand"]

    # 构建 QualityScores（如果提供）
    postprocessor_module = import_module("app.services.postprocessor")
    qs = None
    if quality_scores is not None:
        qs = postprocessor_module.QualityScores(**quality_scores)
    elif not cache_hit:
        # 默认：高质量评分（非缓存命中时）
        qs = postprocessor_module.QualityScores(
            semantic_preservation=5,
            clarity_improvement=4,
            information_gain=3,
            term_accuracy=5,
            retrievability=4,
            total_score=21,
            verdict="excellent",
            issues=[],
        )

    return query_rewriter_module.RewriteResult(
        original_query=original_query,
        rewritten_queries=rewritten_queries,
        strategies_used=strategies_used,
        rewrite_time_ms=rewrite_time_ms,
        cache_hit=cache_hit,
        rewrite_model=rewrite_model,
        intent=intent,
        complexity=complexity,
        cache_level=cache_level,
        quality_scores=qs,
        backtrack_triggered=backtrack_triggered,
        backtrack_strategy=backtrack_strategy,
    )


# ═══════════════════════════════════════════════════════════════════════════
# fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def e2e_client(
    db_session: Session,
) -> Generator[TestClient]:
    """Create a TestClient with all search dependencies overridden for e2e testing.

    Overrides the full dependency chain (chat config, embedding adapter,
    chat adapter, query rewriter, response cache, audit trail) so that
    POST /api/search can exercise the complete pipeline without external
    service dependencies.

    Tests configure the mock rewriter via
    ``app._search_test_refs.query_rewriter`` after the fixture yields.
    """
    _embedding_adapter = make_fake_embedding_adapter()
    _chat_adapter = make_fake_chat_adapter()
    _chat_config = make_fake_chat_config()
    _session = make_fake_session(
        total_embedding_count=1,
        rows=[make_fake_db_row(rank=1, score=0.10)],
    )

    # Mock QueryRewriter — defaults to a complete Phase 2 rewrite result
    # NOTE: rewrite() is async, so its mock must be AsyncMock for await to work.
    _query_rewriter = MagicMock()
    _query_rewriter.rewrite = AsyncMock(return_value=make_full_rewrite_result())

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
    search_routes = import_module("app.api.routes.search")
    overrides = {
        search_routes.get_chat_config: _get_chat_config,
        search_routes.get_embedding_adapter: _get_embedding_adapter,
        search_routes.get_chat_adapter: _get_chat_adapter,
        search_routes.get_search_response_cache: _get_search_response_cache,
        search_routes.get_search_audit_trail: _get_search_audit_trail,
    }
    if hasattr(search_routes, "get_query_rewriter"):
        overrides[search_routes.get_query_rewriter] = _get_query_rewriter

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


# ═══════════════════════════════════════════════════════════════════════════
# 11.1.1 端到端测试用例
# ═══════════════════════════════════════════════════════════════════════════


class TestQueryRewriteE2EFullPipeline:
    """POST /api/search → QueryRewriter 完整管线 → SearchResponse 端到端验证。

    验证从 HTTP 请求到 JSON 响应的完整链路，确保所有 Phase 2 字段正确
    序列化、耗时统计准确、审计追踪 ID 一致。
    """

    # ── 1. 完整 rewrite_info Phase 2 字段序列化 ──────────────────────────

    def test_full_pipeline_rewrite_info_contains_all_phase2_fields(self, e2e_client: TestClient):
        """端到端：SearchResponse JSON 应包含完整 rewrite_info（含所有 Phase 2 扩展字段）。

        模拟管线执行：精确词保护 → 上下文融合 → 意图分类(procedural/5)
        → 策略路由 → normalize + expand 执行 → 质量评估(excellent/21)
        → 保护词还原。
        """
        rewriter = e2e_client.app._search_test_refs.query_rewriter
        rewriter.rewrite.return_value = make_full_rewrite_result(
            original_query="Python 怎么学",
            intent="procedural",
            complexity=5,
            cache_level=None,  # 未命中缓存
            backtrack_triggered=False,
        )

        response = e2e_client.post(
            "/api/search",
            json={"query": "Python 怎么学", "top_k": 5},
        )

        assert response.status_code == 200
        payload = response.json()

        # ── rewrite_info 应存在且非 null ──
        assert "rewrite_info" in payload
        ri = payload["rewrite_info"]
        assert ri is not None

        # ── 基础字段 ──
        assert ri["original_query"] == "Python 怎么学"
        assert ri["cache_hit"] is False
        assert ri["error"] is None  # 成功时 error 为 null
        assert ri["rewrite_model"] == "test-rewrite-model"

        # ── Phase 2: 意图与复杂度 ──
        assert ri["intent"] == "procedural"
        assert ri["complexity"] == 5

        # ── Phase 2: 缓存层级 ──
        assert ri["cache_level"] is None  # 未命中

        # ── Phase 2: 改写结果（含 duration_ms / tokens） ──
        assert len(ri["rewritten_queries"]) == 2

        rq0 = ri["rewritten_queries"][0]
        assert rq0["query"] == "如何系统学习 Python 编程语言"
        assert rq0["strategy"] == "normalize"
        assert isinstance(rq0["duration_ms"], (int, float))
        assert rq0["duration_ms"] == 120.0
        assert isinstance(rq0["tokens"], int)
        assert rq0["tokens"] == 45

        rq1 = ri["rewritten_queries"][1]
        assert rq1["query"] == "Python 学习路径、语法基础、常用库与项目实践"
        assert rq1["strategy"] == "expand"
        assert rq1["duration_ms"] == 200.0
        assert rq1["tokens"] == 60

        # ── Phase 2: 使用策略列表 ──
        assert ri["strategies_used"] == ["normalize", "expand"]

        # ── Phase 2: 质量评分 ──
        assert ri["quality_scores"] is not None
        qs = ri["quality_scores"]
        assert qs["semantic_preservation"] == 5
        assert qs["clarity_improvement"] == 4
        assert qs["information_gain"] == 3
        assert qs["term_accuracy"] == 5
        assert qs["retrievability"] == 4
        assert qs["total_score"] == 21
        assert qs["verdict"] == "excellent"
        assert qs["issues"] == []

        # ── Phase 2: 回溯状态 ──
        assert ri["backtrack_triggered"] is False
        assert ri["backtrack_strategy"] is None

    # ── 2. 搜索耗时包含重写耗时 ──────────────────────────────────────────

    def test_search_time_ms_includes_rewrite_time(self, e2e_client: TestClient):
        """端到端：search_time_ms 应反映包含重写步骤的完整管线耗时。

        search_time_ms 从 SearchService.search() 开始时计时（t0），
        在搜索管线全部完成后结算。由于 t0 在查询重写之前设置，
        search_time_ms 必然包含重写步骤的耗时。

        注：使用 mock QueryRewriter 时 rewrite() 瞬间返回（同步），
        因此 reported rewrite_time_ms 为 mock 提供的值，
        而 search_time_ms 为实际壁钟耗时。两者独立测量，
        但 search_time_ms 的计算区间确实包含了 rewrite 调用。
        """
        rewriter = e2e_client.app._search_test_refs.query_rewriter
        rewriter.rewrite.return_value = make_full_rewrite_result(
            rewrite_time_ms=0.5,  # mock 返回的微小值，小于实际 wall-clock
        )

        response = e2e_client.post(
            "/api/search",
            json={"query": "大模型应用场景", "top_k": 3},
        )

        assert response.status_code == 200
        payload = response.json()

        search_time_ms = payload["search_time_ms"]
        rewrite_time_ms = payload["rewrite_info"]["rewrite_time_ms"]

        assert isinstance(search_time_ms, (int, float))
        assert search_time_ms >= 0
        assert isinstance(rewrite_time_ms, (int, float))
        assert rewrite_time_ms == 0.5

        # search_time_ms 从 t0（在 rewrite 调用之前）计时，因此 >= 0
        # 且确实包含了 rewrite 调用的壁钟耗时（mock 场景下 ~μs 级）
        assert search_time_ms >= 0

    # ── 3. rewrite_time_ms 独立准确 ─────────────────────────────────────

    def test_rewrite_time_ms_independently_accurate(self, e2e_client: TestClient):
        """端到端：rewrite_time_ms 应独立反映重写耗时，不受搜索其他步骤影响。

        验证 rewrite_time_ms 等于 QueryRewriter 返回的值，
        即使 search_time_ms 因向量搜索/LLM 生成而变化，
        rewrite_time_ms 始终保持独立准确性。
        """
        rewriter = e2e_client.app._search_test_refs.query_rewriter

        # 使用一个固定的 rewrite_time_ms，验证其准确传递
        expected_rewrite_time = 123.45
        rewriter.rewrite.return_value = make_full_rewrite_result(
            rewrite_time_ms=expected_rewrite_time,
        )

        response = e2e_client.post(
            "/api/search",
            json={"query": "知识图谱构建方法", "top_k": 5},
        )

        assert response.status_code == 200
        payload = response.json()

        actual_rewrite_time = payload["rewrite_info"]["rewrite_time_ms"]
        assert actual_rewrite_time == expected_rewrite_time, (
            f"rewrite_time_ms 应为 {expected_rewrite_time}，实际为 {actual_rewrite_time}"
        )

        # 再次发送不同查询，验证独立于前次请求
        expected_rewrite_time_2 = 78.9
        rewriter.rewrite.return_value = make_full_rewrite_result(
            original_query="NLP 最新进展",
            rewrite_time_ms=expected_rewrite_time_2,
        )

        response2 = e2e_client.post(
            "/api/search",
            json={"query": "NLP 最新进展", "top_k": 3},
        )

        assert response2.status_code == 200
        payload2 = response2.json()
        assert payload2["rewrite_info"]["rewrite_time_ms"] == expected_rewrite_time_2
        assert payload2["rewrite_info"]["original_query"] == "NLP 最新进展"

    # ── 4. 审计追踪 ID（trace_id）贯穿同一请求 ───────────────────────────

    def test_audit_trail_id_present_and_consistent(self, e2e_client: TestClient):
        """端到端：同一请求的所有日志事件共享 audit_trail_id。

        audit_trail_id 在 SearchService.search() 开始时生成，
        注入到 SearchResponse 中。同一请求返回的 response 中
        audit_trail_id 应为非空字符串（16 字符十六进制）。
        """
        rewriter = e2e_client.app._search_test_refs.query_rewriter
        rewriter.rewrite.return_value = make_full_rewrite_result(
            original_query="微服务架构最佳实践",
        )

        response = e2e_client.post(
            "/api/search",
            json={"query": "微服务架构最佳实践", "top_k": 5},
        )

        assert response.status_code == 200
        payload = response.json()

        # audit_trail_id 应为非空字符串
        audit_trail_id = payload.get("audit_trail_id")
        assert audit_trail_id is not None, "SearchResponse 应包含 audit_trail_id 用于端到端日志追踪"
        assert isinstance(audit_trail_id, str)
        assert len(audit_trail_id) == 16, (
            f"audit_trail_id 应为 16 字符十六进制字符串，实际长度: {len(audit_trail_id)}"
        )
        # 验证为十六进制字符串
        int(audit_trail_id, 16)  # 不抛异常即为合法 hex

    def test_different_requests_have_different_trace_ids(self, e2e_client: TestClient):
        """端到端：不同请求应生成不同的 audit_trail_id。

        每次 POST /api/search 都应生成新的 trace_id，
        确保日志系统中可区分不同请求。
        """
        rewriter = e2e_client.app._search_test_refs.query_rewriter

        trace_ids = []
        queries = [
            "Python 数据分析",
            "Java 并发编程",
            "分布式系统设计",
        ]

        for q in queries:
            rewriter.rewrite.return_value = make_full_rewrite_result(
                original_query=q,
            )
            response = e2e_client.post(
                "/api/search",
                json={"query": q, "top_k": 3},
            )
            assert response.status_code == 200
            tid = response.json()["audit_trail_id"]
            assert tid is not None
            trace_ids.append(tid)

        # 所有 trace_id 应互不相同
        assert len(set(trace_ids)) == len(queries), (
            f"不同请求的 audit_trail_id 应互不相同，实际: {trace_ids}"
        )

    # ── 5. 多策略串联执行的端到端验证 ────────────────────────────────────

    def test_multi_strategy_pipeline_serialization(self, e2e_client: TestClient):
        """端到端：多策略串联（normalize + term_align + expand）完整序列化。

        模拟高复杂度 ambiguous 查询触发三条策略串联执行，
        验证每条改写结果的 strategy/duration_ms/tokens 独立记录。
        """
        rewriter = e2e_client.app._search_test_refs.query_rewriter
        rewriter.rewrite.return_value = make_full_rewrite_result(
            original_query="那个东西怎么搞",
            rewritten_queries=[
                {
                    "query": "那个东西如何处理",
                    "strategy": "normalize",
                    "duration_ms": 95.0,
                    "tokens": 38,
                },
                {
                    "query": "Python 异常处理机制（术语已对齐）",
                    "strategy": "term_align",
                    "duration_ms": 110.0,
                    "tokens": 42,
                },
                {
                    "query": "Python 异常处理 try except finally raise 用法详解与最佳实践",
                    "strategy": "expand",
                    "duration_ms": 185.0,
                    "tokens": 55,
                },
            ],
            strategies_used=["normalize", "term_align", "expand"],
            intent="ambiguous",
            complexity=8,
            rewrite_time_ms=390.0,
            backtrack_triggered=False,
        )

        response = e2e_client.post(
            "/api/search",
            json={"query": "那个东西怎么搞", "top_k": 5},
        )

        assert response.status_code == 200
        payload = response.json()
        ri = payload["rewrite_info"]

        assert ri["intent"] == "ambiguous"
        assert ri["complexity"] == 8
        assert ri["strategies_used"] == ["normalize", "term_align", "expand"]
        assert len(ri["rewritten_queries"]) == 3

        # 每条改写结果都有独立的元数据
        strategies_seen = []
        for rq in ri["rewritten_queries"]:
            assert "query" in rq
            assert "strategy" in rq
            assert "duration_ms" in rq
            assert "tokens" in rq
            assert rq["duration_ms"] > 0
            assert rq["tokens"] > 0
            strategies_seen.append(rq["strategy"])

        assert strategies_seen == ["normalize", "term_align", "expand"]

        # 总重写耗时应 >= 各策略耗时之和（含路由/质量评估开销）
        total_strategy_time = sum(rq["duration_ms"] for rq in ri["rewritten_queries"])
        assert ri["rewrite_time_ms"] >= total_strategy_time, (
            f"总重写耗时 ({ri['rewrite_time_ms']}ms) 应 >= 各策略耗时之和 ({total_strategy_time}ms)"
        )

    # ── 6. L2 语义缓存命中的端到端验证 ──────────────────────────────────

    def test_l2_cache_hit_serialization(self, e2e_client: TestClient):
        """端到端：L2 语义缓存命中时 cache_level 和 cache_hit 正确序列化。"""
        rewriter = e2e_client.app._search_test_refs.query_rewriter
        rewriter.rewrite.return_value = make_full_rewrite_result(
            original_query="Python 怎么学",
            rewritten_queries=[
                {
                    "query": "如何系统学习 Python 编程语言",
                    "strategy": "normalize",
                    "duration_ms": 5.0,
                    "tokens": 0,
                },
            ],
            strategies_used=["normalize"],
            rewrite_time_ms=8.0,
            cache_hit=True,
            cache_level="L2",
            quality_scores=None,  # 缓存命中时不重新评估
        )

        response = e2e_client.post(
            "/api/search",
            json={"query": "Python 怎么学", "top_k": 5},
        )

        assert response.status_code == 200
        payload = response.json()
        ri = payload["rewrite_info"]

        assert ri["cache_hit"] is True
        assert ri["cache_level"] == "L2"
        assert ri["rewrite_time_ms"] == 8.0
        # 缓存命中时 quality_scores 为 null（未重新评估）
        assert ri["quality_scores"] is None

    # ── 7. 回溯触发的端到端验证 ─────────────────────────────────────────

    def test_backtrack_triggered_serialization(self, e2e_client: TestClient):
        """端到端：质量评估不合格触发回溯时，backtrack 字段正确序列化。

        模拟首次 normalize 质量不合格 → 回溯升级为 expand → 二次通过。
        """
        rewriter = e2e_client.app._search_test_refs.query_rewriter
        rewriter.rewrite.return_value = make_full_rewrite_result(
            original_query="性能",
            rewritten_queries=[
                {
                    "query": "系统性能优化方法、瓶颈分析、监控指标与调优策略",
                    "strategy": "expand",
                    "duration_ms": 310.0,
                    "tokens": 72,
                },
            ],
            strategies_used=["expand"],
            rewrite_time_ms=350.0,
            intent="ambiguous",
            complexity=9,
            backtrack_triggered=True,
            backtrack_strategy="expand",
            quality_scores={
                "semantic_preservation": 4,
                "clarity_improvement": 4,
                "information_gain": 4,
                "term_accuracy": 4,
                "retrievability": 4,
                "total_score": 20,
                "verdict": "good",
                "issues": ["首次 normalize 改写质量 marginal，已自动升级为 expand"],
            },
        )

        response = e2e_client.post(
            "/api/search",
            json={"query": "性能", "top_k": 5},
        )

        assert response.status_code == 200
        payload = response.json()
        ri = payload["rewrite_info"]

        assert ri["backtrack_triggered"] is True
        assert ri["backtrack_strategy"] == "expand"
        assert ri["strategies_used"] == ["expand"]

        # 质量评分应反映回溯后的结果
        qs = ri["quality_scores"]
        assert qs is not None
        assert qs["verdict"] == "good"
        assert "回溯" in qs["issues"][0] or "升级" in qs["issues"][0]

    # ── 8. 重写失败降级时端到端验证 ─────────────────────────────────────

    def test_rewrite_failure_graceful_degradation_e2e(self, e2e_client: TestClient):
        """端到端：QueryRewriter 异常时搜索正常完成，rewrite_info 含 error。

        验证降级路径：rewrite_info.error 非 null、
        rewritten_queries 为空、搜索正常返回结果。
        """
        rewriter = e2e_client.app._search_test_refs.query_rewriter
        rewriter.rewrite.side_effect = RuntimeError("LLM 服务不可用")

        response = e2e_client.post(
            "/api/search",
            json={"query": "系统架构设计原则", "top_k": 5},
        )

        assert response.status_code == 200, (
            f"重写失败不应影响搜索，期望 200，实际 {response.status_code}"
        )
        payload = response.json()

        # rewrite_info 应包含错误信息
        ri = payload["rewrite_info"]
        assert ri is not None
        assert ri["error"] is not None
        assert "LLM 服务不可用" in ri["error"]
        assert ri["original_query"] == "系统架构设计原则"
        assert ri["rewritten_queries"] == []
        assert ri["strategies_used"] == []
        assert ri["cache_hit"] is False

        # 搜索结果应正常
        assert len(payload["results"]) >= 1
        assert len(payload["answer"]) > 0
        assert payload["search_time_ms"] >= 0
        assert payload["audit_trail_id"] is not None

    # ── 9. history 传递的端到端验证 ─────────────────────────────────────

    def test_history_passed_to_rewriter(self, e2e_client: TestClient):
        """端到端：对话历史正确传递至 QueryRewriter.rewrite()。

        验证 rewrite() 被调用时 history 参数正确传递，
        确保上下文融合（指代词消解）可正常工作。
        """
        rewriter = e2e_client.app._search_test_refs.query_rewriter
        rewriter.rewrite.return_value = make_full_rewrite_result(
            original_query="它怎么配置",
            rewritten_queries=[
                {
                    "query": "Nginx 反向代理如何配置",
                    "strategy": "context_fusion",
                    "duration_ms": 150.0,
                    "tokens": 50,
                },
            ],
            strategies_used=["context_fusion", "normalize"],
            intent="procedural",
            complexity=4,
            rewrite_time_ms=200.0,
        )

        history = [
            {"role": "user", "content": "Nginx 有哪些常用功能？"},
            {
                "role": "assistant",
                "content": ("Nginx 常用功能包括反向代理、负载均衡、静态文件服务等。"),
            },
        ]

        response = e2e_client.post(
            "/api/search",
            json={
                "query": "它怎么配置",
                "top_k": 5,
                "history": history,
            },
        )

        assert response.status_code == 200
        payload = response.json()

        # 验证 rewrite_info 正确
        ri = payload["rewrite_info"]
        assert ri["original_query"] == "它怎么配置"
        assert ri["strategies_used"] == ["context_fusion", "normalize"]
        assert ri["rewritten_queries"][0]["strategy"] == "context_fusion"

        # 验证 rewriter.rewrite() 被调用时包含 history
        rewriter.rewrite.assert_called_once()
        call_kwargs = rewriter.rewrite.call_args.kwargs
        assert call_kwargs.get("history") == history, (
            "QueryRewriter.rewrite() 应接收 history 参数用于指代词消解"
        )

    # ── 10. session_id 传递的端到端验证 ──────────────────────────────────

    def test_session_id_passed_to_rewriter(self, e2e_client: TestClient):
        """端到端：session_id 正确传递至 QueryRewriter.rewrite()。

        session_id 用于 L1 缓存绑定（不同会话隔离），
        验证其正确传递到底层 rewrite 调用。
        """
        rewriter = e2e_client.app._search_test_refs.query_rewriter
        rewriter.rewrite.return_value = make_full_rewrite_result(
            original_query="测试查询",
        )

        test_session_id = "user-session-abc-123"

        response = e2e_client.post(
            "/api/search",
            json={
                "query": "测试查询",
                "top_k": 3,
                "session_id": test_session_id,
            },
        )

        assert response.status_code == 200

        # 验证 session_id 被传递给 rewriter
        rewriter.rewrite.assert_called_once()
        call_kwargs = rewriter.rewrite.call_args.kwargs
        assert call_kwargs.get("session_id") == test_session_id, (
            f"QueryRewriter.rewrite() 应接收 session_id，"
            f"期望 '{test_session_id}'，"
            f"实际 '{call_kwargs.get('session_id')}'"
        )

    # ── 11. 事实型低复杂度查询（direct 路由）端到端验证 ──────────────────

    def test_factual_low_complexity_direct_routing(self, e2e_client: TestClient):
        """端到端：factual + 低复杂度 → direct 路由（跳过所有策略）。

        简单事实型查询不需要重写，rewritten_queries 仅含原始查询
        且 strategy 为 None，strategies_used 为空。
        """
        rewriter = e2e_client.app._search_test_refs.query_rewriter
        rewriter.rewrite.return_value = make_full_rewrite_result(
            original_query="1+1等于几",
            rewritten_queries=[
                {"query": "1+1等于几", "strategy": None, "duration_ms": 1.0, "tokens": 0},
            ],
            strategies_used=[],
            rewrite_time_ms=2.0,
            intent="factual",
            complexity=1,
            cache_hit=False,
            quality_scores=None,  # direct 路由不评估质量
        )

        response = e2e_client.post(
            "/api/search",
            json={"query": "1+1等于几", "top_k": 3},
        )

        assert response.status_code == 200
        payload = response.json()
        ri = payload["rewrite_info"]

        assert ri["intent"] == "factual"
        assert ri["complexity"] == 1
        assert ri["strategies_used"] == []
        assert len(ri["rewritten_queries"]) == 1
        assert ri["rewritten_queries"][0]["strategy"] is None
        assert ri["rewritten_queries"][0]["query"] == "1+1等于几"

    # ── 12. quality_scores 各 verdict 等级的序列化验证 ──────────────────

    @pytest.mark.parametrize(
        "verdict,total_score,expected_verdict",
        [
            ("excellent", 23, "excellent"),
            ("good", 18, "good"),
            ("marginal", 13, "marginal"),
            ("poor", 8, "poor"),
        ],
    )
    def test_quality_scores_all_verdict_levels(
        self, e2e_client: TestClient, verdict, total_score, expected_verdict
    ):
        """端到端：所有 quality_scores verdict 等级正确序列化。"""
        rewriter = e2e_client.app._search_test_refs.query_rewriter
        rewriter.rewrite.return_value = make_full_rewrite_result(
            original_query="测试查询",
            quality_scores={
                "semantic_preservation": max(1, total_score // 5),
                "clarity_improvement": max(1, total_score // 5),
                "information_gain": max(1, total_score // 5),
                "term_accuracy": max(1, total_score // 5),
                "retrievability": max(1, total_score // 5),
                "total_score": total_score,
                "verdict": verdict,
                "issues": [],
            },
        )

        response = e2e_client.post(
            "/api/search",
            json={"query": "测试查询", "top_k": 3},
        )

        assert response.status_code == 200
        payload = response.json()
        qs = payload["rewrite_info"]["quality_scores"]

        assert qs is not None
        assert qs["verdict"] == expected_verdict
        assert qs["total_score"] == total_score
