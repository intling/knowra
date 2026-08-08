"""Shared test fixtures for query_rewriter tests.

Provides mock adapters, Phase 2 fixtures, and sample data used across all
query rewriter test modules.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# ── mock_chat_adapter ─────────────────────────────────────────────────────


@pytest.fixture
def mock_chat_adapter() -> MagicMock:
    """A ChatAdapter mock that returns a controllable LLM response.

    Default behaviour:
    - ``generate()`` returns a ChatResult with content ``"这是一个改写后的查询"``
      and model ``"test-rewrite-model"``.

    Tests can override the return value per-case via
    ``mock_chat_adapter.generate.return_value = ...``.
    """
    from app.services.chat_adapter import ChatResult

    adapter = MagicMock()
    adapter.config = SimpleNamespace(
        model="test-rewrite-model",
        temperature=0.1,
        max_tokens=512,
    )
    adapter.generate = MagicMock(
        return_value=ChatResult(
            content="这是一个改写后的查询",
            model="test-rewrite-model",
            prompt_tokens=50,
            completion_tokens=20,
            total_tokens=70,
        )
    )
    return adapter


# ── mock_embedding_adapter ────────────────────────────────────────────────


@pytest.fixture
def mock_embedding_adapter() -> MagicMock:
    """An EmbeddingAdapter mock that returns a fixed 4-d vector.

    Tests can override the return value per-case via
    ``mock_embedding_adapter.embed_single.return_value = ...``.
    """
    from app.services.embedding_adapter import EmbeddingResult

    adapter = MagicMock()
    adapter.config = SimpleNamespace(
        model="test-embed-model",
        dimensions=4,
    )
    adapter.embed_single = MagicMock(
        return_value=EmbeddingResult(
            index=0,
            embedding=[0.1, 0.2, 0.3, 0.4],
            token_count=10,
        )
    )
    return adapter


# ── sample_rewrite_result ─────────────────────────────────────────────────


@pytest.fixture
def sample_rewrite_result() -> dict:
    """A sample RewriteResult-like dict used as a shared test fixture.

    Contains the fields expected in a complete rewrite result:
    original_query, rewritten_queries (list of {query, strategy}),
    strategies_used, rewrite_time_ms, cache_hit, and rewrite_model.
    """
    return {
        "original_query": "它怎么用",
        "rewritten_queries": [
            {"query": "Python 怎么使用", "strategy": "context_fusion"},
            {"query": "Python 如何使用", "strategy": "normalize"},
        ],
        "strategies_used": ["context_fusion", "normalize"],
        "rewrite_time_ms": 45.2,
        "cache_hit": False,
        "rewrite_model": None,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2 共享 fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_strategy_router() -> MagicMock:
    """Mock StrategyRouter —— 默认返回 factual+低复杂度，路由为 direct。

    测试可按需覆盖 ``route.return_value``。
    """
    router = MagicMock()
    router.route.return_value = {
        "intent": "factual",
        "complexity": 1,
        "strategies": [],  # direct → 跳过所有策略
    }
    return router


@pytest.fixture
def mock_normalize_rewriter() -> MagicMock:
    """Mock NormalizeRewriter —— 默认返回规范化后的查询。"""
    rewriter = MagicMock()
    rewriter.rewrite.return_value = {
        "query": "如何学习 Python",
        "strategy": "normalize",
        "duration_ms": 120.0,
        "tokens": 45,
    }
    return rewriter


@pytest.fixture
def mock_term_align_rewriter() -> MagicMock:
    """Mock TermAlignRewriter —— 默认返回术语对齐后的查询。"""
    rewriter = MagicMock()
    rewriter.rewrite.return_value = {
        "query": "如何学习 Python（术语已对齐）",
        "strategy": "term_align",
        "duration_ms": 80.0,
        "tokens": 35,
    }
    return rewriter


@pytest.fixture
def mock_expand_rewriter() -> MagicMock:
    """Mock ExpandRewriter —— 默认返回扩展后的查询。"""
    rewriter = MagicMock()
    rewriter.rewrite.return_value = {
        "query": "Python 学习路径、语法基础、常用库、项目实践",
        "strategy": "expand",
        "duration_ms": 200.0,
        "tokens": 60,
    }
    return rewriter


@pytest.fixture
def mock_cache_manager_with_l2() -> MagicMock:
    """Mock CacheManager —— 默认 L1/L2 均未命中。

    ``lookup_l2`` 接受 query_vector 参数，默认返回 None。
    """
    cache = MagicMock()
    cache.lookup.return_value = None  # L1: (session_id, query_hash) → Any | None
    cache.lookup_l2.return_value = None  # L2: (query_vector) → Any | None
    return cache


@pytest.fixture
def mock_protector_phase2() -> MagicMock:
    """Mock ExactTermProtector —— 默认透传查询，无保护词。"""
    protector = MagicMock()
    protector.protect.return_value = ("test query", {})
    protector.restore.return_value = "test query"
    return protector


@pytest.fixture
def mock_context_rewriter_phase2() -> MagicMock:
    """Mock ContextRewriter —— 默认返回融合后的查询。"""
    rewriter = MagicMock()
    rewriter.rewrite.return_value = "rewritten query with context"
    return rewriter


@pytest.fixture
def mock_audit_trail_phase2() -> MagicMock:
    """Mock AuditTrail —— 静默记录。"""
    return MagicMock()


@pytest.fixture
def mock_dissatisfaction_detector() -> MagicMock:
    """Mock DissatisfactionDetector —— 默认未检测到不满意重试信号。

    提供 ``check`` 方法（返回 ``True`` 表示检测到不满意重试）
    和 ``record`` 方法（记录当前查询用于后续检测）。
    测试可按需覆盖 ``check.return_value``。
    """
    detector = MagicMock()
    detector.check.return_value = False  # 默认：不是重试
    return detector


@pytest.fixture
def mock_context_verifier() -> MagicMock:
    """Mock 轻量级上下文相关性校验器。

    默认返回验证通过（``context_dependent=False``），测试可按需覆盖。
    """
    verifier = MagicMock()
    verifier.verify.return_value = {
        "context_dependent": False,
        "reasoning": "Answer is general knowledge, not dependent on specific context.",
    }
    return verifier


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2 共享辅助函数
# ═══════════════════════════════════════════════════════════════════════════


def build_phase2_rewriter(
    *,
    protector=None,
    context_rewriter=None,
    cache_manager=None,
    chat_adapter=None,
    audit_trail=None,
    strategy_router=None,
    normalize_rewriter=None,
    term_align_rewriter=None,
    expand_rewriter=None,
    dissatisfaction_detector=None,
    context_verifier=None,
    enabled: bool = True,
    pipeline_timeout: float = 20.0,
    strategy_timeout: float = 10.0,
    dissatisfaction_window_seconds: float = 60.0,
    strategy_normalize_enabled: bool = True,
    strategy_expand_enabled: bool = True,
    strategy_term_align_enabled: bool = True,
):
    """构建 Phase 2 增强后的 QueryRewriter 实例。"""
    from app.services.query_rewriter import QueryRewriter

    protector = protector or MagicMock()
    context_rewriter = context_rewriter or MagicMock()
    cache_manager = cache_manager or MagicMock()
    chat_adapter = chat_adapter or MagicMock()
    audit_trail = audit_trail or MagicMock()
    strategy_router = strategy_router or MagicMock()
    normalize_rewriter = normalize_rewriter or MagicMock()
    term_align_rewriter = term_align_rewriter or MagicMock()
    expand_rewriter = expand_rewriter or MagicMock()
    dissatisfaction_detector = dissatisfaction_detector  # None 时不创建默认 mock
    return QueryRewriter(
        exact_term_protector=protector,
        context_rewriter=context_rewriter,
        cache_manager=cache_manager,
        chat_adapter=chat_adapter,
        audit_trail=audit_trail,
        strategy_router=strategy_router,
        normalize_rewriter=normalize_rewriter,
        term_align_rewriter=term_align_rewriter,
        expand_rewriter=expand_rewriter,
        dissatisfaction_detector=dissatisfaction_detector,
        context_verifier=context_verifier,
        enabled=enabled,
        pipeline_timeout=pipeline_timeout,
        strategy_timeout=strategy_timeout,
        dissatisfaction_window_seconds=dissatisfaction_window_seconds,
        strategy_normalize_enabled=strategy_normalize_enabled,
        strategy_expand_enabled=strategy_expand_enabled,
        strategy_term_align_enabled=strategy_term_align_enabled,
    )


def make_l2_cache_entry(
    result,
    similarity: float,
    knowledge_type: str = "general_knowledge",
    source_session_id: str | None = "original_session",
) -> dict:
    """构建 L2 缓存查询返回值 —— 包含结果与元数据。

    Args:
        result: 缓存的 RewriteResult。
        similarity: 语义相似度（0.0–1.0）。
        knowledge_type: 知识类型 —— ``"general_knowledge"`` 或 ``"context_dependent"``。
        source_session_id: 来源会话 ID（仅 context_dependent 需要，
            用于跨会话拦截）。为 ``None`` 时表示未知来源。

    Returns:
        模拟 ``CacheManager.lookup_l2(query_vector)`` 返回的 dict。
    """
    return {
        "result": result,
        "similarity": similarity,
        "knowledge_type": knowledge_type,
        "source_session_id": source_session_id,
    }
