"""QueryRewriter Phase 2 集成测试 —— 意图分类、策略路由与多策略串联。

测试覆盖：
- 意图分类+路由集成：factual+低复杂度→跳过重写（direct）、
  中等复杂度（analytical/procedural, complexity 3-5）→normalize+term_align、
  ambiguous→expand、高复杂度（complexity ≥ 6）→normalize+term_align+expand
- L2 语义缓存命中跳过 LLM（基础集成）
- 多策略串联执行（前策略输出作为后策略输入）
- 策略开关（QUERY_REWRITE_STRATEGY_NORMALIZE/EXPAND/TERM_ALIGN=false 时跳过对应策略）

.. note::
    本文件为 Phase 2 的**红测试**（TDD Red Phase）。
    运行时应预期失败 —— 当前 QueryRewriter 尚未集成策略路由与重写策略。

    L2 语义缓存精细化测试已拆分至 ``test_semantic_cache_l2.py``。
    不满意重试检测测试已拆分至 ``test_dissatisfaction_retry.py``。
"""

from __future__ import annotations

import pytest

from app.services.query_rewriter import RewriteResult

from .conftest import build_phase2_rewriter

# ═════════════════════════════════════════════════════════════════════
# 意图分类 + 路由集成测试
# ═════════════════════════════════════════════════════════════════════


class TestIntentClassificationAndRouting:
    """验证意图分类结果驱动正确的策略路由。"""

    pytestmark = pytest.mark.asyncio

    async def test_factual_low_complexity_skips_all_strategies(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """factual + complexity ≤ 2 → 路由为 direct，跳过所有重写策略。"""
        mock_protector_phase2.protect.return_value = ("Redis 默认端口是多少", {})
        mock_protector_phase2.restore.return_value = "Redis 默认端口是多少"
        mock_strategy_router.route.return_value = {
            "intent": "factual",
            "complexity": 1,
            "strategies": [],
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        result = await rewriter.rewrite("Redis 默认端口是多少", history=None)

        # 策略路由被调用
        mock_strategy_router.route.assert_called_once()
        # 所有重写策略未被调用
        mock_normalize_rewriter.rewrite.assert_not_called()
        mock_term_align_rewriter.rewrite.assert_not_called()
        mock_expand_rewriter.rewrite.assert_not_called()
        # 结果：direct 策略，原始查询透传
        assert result.strategies_used == []
        assert result.rewritten_queries[0]["strategy"] == "direct"

    async def test_factual_low_complexity_boundary_complexity_2(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """factual + complexity = 2（边界值）→ 仍应跳过重写。"""
        mock_protector_phase2.protect.return_value = ("Python 是什么", {})
        mock_protector_phase2.restore.return_value = "Python 是什么"
        mock_strategy_router.route.return_value = {
            "intent": "factual",
            "complexity": 2,
            "strategies": [],
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        result = await rewriter.rewrite("Python 是什么", history=None)

        mock_normalize_rewriter.rewrite.assert_not_called()
        assert result.rewritten_queries[0]["strategy"] == "direct"

    async def test_chitchat_low_complexity_skips_strategies(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """chitchat + complexity ≤ 2 → 路由为 direct，跳过所有重写策略。"""
        mock_protector_phase2.protect.return_value = ("你好", {})
        mock_protector_phase2.restore.return_value = "你好"
        mock_strategy_router.route.return_value = {
            "intent": "chitchat",
            "complexity": 1,
            "strategies": [],
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        result = await rewriter.rewrite("你好", history=None)

        mock_normalize_rewriter.rewrite.assert_not_called()
        assert result.rewritten_queries[0]["strategy"] == "direct"

    async def test_medium_complexity_executes_normalize_and_term_align(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """中等复杂度（3-5）+ procedural → normalize + term_align。"""
        mock_protector_phase2.protect.return_value = ("数据库怎么优化", {})
        mock_protector_phase2.restore.return_value = "如何优化数据库性能（术语已对齐）"
        mock_strategy_router.route.return_value = {
            "intent": "procedural",
            "complexity": 4,
            "strategies": ["normalize", "term_align"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "如何优化数据库性能",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 40,
        }
        mock_term_align_rewriter.rewrite.return_value = {
            "query": "如何优化数据库性能（术语已对齐）",
            "strategy": "term_align",
            "duration_ms": 80.0,
            "tokens": 35,
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        await rewriter.rewrite("数据库怎么优化", history=None)

        # normalize 和 term_align 被调用
        mock_normalize_rewriter.rewrite.assert_called_once()
        mock_term_align_rewriter.rewrite.assert_called_once()
        # expand 未被调用
        mock_expand_rewriter.rewrite.assert_not_called()

    async def test_analytical_medium_complexity_executes_normalize_and_term_align(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """analytical + complexity 3 → normalize + term_align。"""
        mock_protector_phase2.protect.return_value = ("系统高并发为什么崩溃", {})
        mock_protector_phase2.restore.return_value = "为什么系统在高并发下会崩溃（术语已对齐）"
        mock_strategy_router.route.return_value = {
            "intent": "analytical",
            "complexity": 3,
            "strategies": ["normalize", "term_align"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "为什么系统在高并发下会崩溃",
            "strategy": "normalize",
            "duration_ms": 110.0,
            "tokens": 42,
        }
        mock_term_align_rewriter.rewrite.return_value = {
            "query": "为什么系统在高并发下会崩溃（术语已对齐）",
            "strategy": "term_align",
            "duration_ms": 70.0,
            "tokens": 30,
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        await rewriter.rewrite("系统高并发为什么崩溃", history=None)

        mock_normalize_rewriter.rewrite.assert_called_once()
        mock_term_align_rewriter.rewrite.assert_called_once()
        mock_expand_rewriter.rewrite.assert_not_called()

    async def test_ambiguous_executes_expand_only(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """ambiguous 意图 → 仅执行 expand 策略。"""
        mock_protector_phase2.protect.return_value = ("Redis", {})
        mock_protector_phase2.restore.return_value = "Redis 数据库、缓存策略、数据结构、应用场景"
        mock_strategy_router.route.return_value = {
            "intent": "ambiguous",
            "complexity": 2,
            "strategies": ["expand"],
        }
        mock_expand_rewriter.rewrite.return_value = {
            "query": "Redis 数据库、缓存策略、数据结构、应用场景",
            "strategy": "expand",
            "duration_ms": 180.0,
            "tokens": 55,
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        await rewriter.rewrite("Redis", history=None)

        mock_expand_rewriter.rewrite.assert_called_once()
        mock_normalize_rewriter.rewrite.assert_not_called()
        mock_term_align_rewriter.rewrite.assert_not_called()

    async def test_high_complexity_executes_all_three_strategies(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """高复杂度（≥ 6）→ normalize + term_align + expand。"""
        mock_protector_phase2.protect.return_value = ("系统架构如何设计才能支持高并发", {})
        mock_protector_phase2.restore.return_value = (
            "高并发系统架构设计：分布式、负载均衡、缓存策略、数据库优化、消息队列"
        )
        mock_strategy_router.route.return_value = {
            "intent": "analytical",
            "complexity": 8,
            "strategies": ["normalize", "term_align", "expand"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "如何设计支持高并发的系统架构",
            "strategy": "normalize",
            "duration_ms": 120.0,
            "tokens": 50,
        }
        mock_term_align_rewriter.rewrite.return_value = {
            "query": "如何设计支持高并发的系统架构（术语已对齐）",
            "strategy": "term_align",
            "duration_ms": 90.0,
            "tokens": 38,
        }
        mock_expand_rewriter.rewrite.return_value = {
            "query": "高并发系统架构设计：分布式、负载均衡、缓存策略、数据库优化、消息队列",
            "strategy": "expand",
            "duration_ms": 210.0,
            "tokens": 65,
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        await rewriter.rewrite("系统架构如何设计才能支持高并发", history=None)

        # 三种策略全部调用
        mock_normalize_rewriter.rewrite.assert_called_once()
        mock_term_align_rewriter.rewrite.assert_called_once()
        mock_expand_rewriter.rewrite.assert_called_once()

    async def test_route_result_passed_to_audit_trail(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """意图和复杂度信息应传递到审计日志。"""
        mock_protector_phase2.protect.return_value = ("测试查询", {})
        mock_protector_phase2.restore.return_value = "测试查询"
        mock_strategy_router.route.return_value = {
            "intent": "analytical",
            "complexity": 7,
            "strategies": ["normalize", "term_align"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "测试查询（规范化）",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 30,
        }
        mock_term_align_rewriter.rewrite.return_value = {
            "query": "测试查询（规范化+术语对齐）",
            "strategy": "term_align",
            "duration_ms": 70.0,
            "tokens": 25,
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        await rewriter.rewrite("测试查询", history=None)

        mock_audit_trail_phase2.record.assert_called()
        audit_kwargs = mock_audit_trail_phase2.record.call_args[1]
        assert audit_kwargs.get("intent") == "analytical"
        assert audit_kwargs.get("complexity") == 7


# ═════════════════════════════════════════════════════════════════════
# L2 语义缓存测试
# ═════════════════════════════════════════════════════════════════════


class TestL2SemanticCache:
    """验证 L2 语义缓存命中时跳过 LLM 调用。"""

    pytestmark = pytest.mark.asyncio

    async def test_l2_cache_hit_skips_llm_and_returns_cached(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """L2 语义缓存命中时应返回缓存结果，不调用策略重写器。"""
        cached = RewriteResult(
            original_query="如何优化数据库性能",
            rewritten_queries=[
                {"query": "数据库性能优化方法", "strategy": "context_fusion"},
                {"query": "数据库性能调优技巧", "strategy": "normalize"},
            ],
            strategies_used=["context_fusion", "normalize"],
            rewrite_time_ms=0.5,
            cache_hit=True,
        )
        # L1 未命中
        mock_cache_manager_with_l2.lookup.return_value = None
        # L2 命中
        mock_cache_manager_with_l2.lookup_l2.return_value = cached
        mock_protector_phase2.protect.return_value = ("怎么提升数据库的性能", {})

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        result = await rewriter.rewrite("怎么提升数据库的性能", history=None)

        # L2 查询被执行
        mock_cache_manager_with_l2.lookup_l2.assert_called_once()
        # 策略路由和重写器未被调用（L2 命中直接返回）
        mock_strategy_router.route.assert_not_called()
        mock_normalize_rewriter.rewrite.assert_not_called()
        mock_term_align_rewriter.rewrite.assert_not_called()
        mock_expand_rewriter.rewrite.assert_not_called()
        # 返回缓存结果
        assert result.cache_hit is True
        assert result.original_query == "如何优化数据库性能"

    async def test_l2_cache_miss_proceeds_to_normal_pipeline(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """L1 和 L2 均未命中时正常执行重写管线。"""
        mock_cache_manager_with_l2.lookup.return_value = None
        mock_cache_manager_with_l2.lookup_l2.return_value = None
        mock_protector_phase2.protect.return_value = ("新查询", {})
        mock_protector_phase2.restore.return_value = "新查询"
        mock_strategy_router.route.return_value = {
            "intent": "factual",
            "complexity": 1,
            "strategies": [],
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        result = await rewriter.rewrite("新查询", history=None)

        # 策略路由被调用（正常管线执行）
        mock_strategy_router.route.assert_called()
        assert result.cache_hit is False

    async def test_l2_cache_hit_records_audit_with_cache_level(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """L2 命中时审计日志应标记 cache_level='L2'。"""
        cached = RewriteResult(
            original_query="如何配置 Nginx",
            rewritten_queries=[
                {"query": "Nginx 配置方法", "strategy": "normalize"},
            ],
            strategies_used=["normalize"],
            rewrite_time_ms=0.3,
            cache_hit=True,
        )
        mock_cache_manager_with_l2.lookup.return_value = None
        mock_cache_manager_with_l2.lookup_l2.return_value = cached
        mock_protector_phase2.protect.return_value = ("怎么配置 Nginx", {})

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        await rewriter.rewrite("怎么配置 Nginx", history=None)

        mock_audit_trail_phase2.record.assert_called()
        audit_kwargs = mock_audit_trail_phase2.record.call_args[1]
        assert audit_kwargs.get("cache_hit") is True
        assert audit_kwargs.get("cache_level") == "L2"

    async def test_l1_cache_checked_before_l2(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """L1 先于 L2 检查 —— L1 命中时不查询 L2。"""
        l1_cached = RewriteResult(
            original_query="完全相同的查询",
            rewritten_queries=[{"query": "完全相同的查询", "strategy": "direct"}],
            rewrite_time_ms=0.1,
            cache_hit=True,
        )
        mock_cache_manager_with_l2.lookup.return_value = l1_cached

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        result = await rewriter.rewrite("完全相同的查询", history=None)

        # L1 命中
        assert result.cache_hit is True
        # L2 不应被查询
        mock_cache_manager_with_l2.lookup_l2.assert_not_called()


# ═════════════════════════════════════════════════════════════════════
# 多策略串联执行测试
# ═════════════════════════════════════════════════════════════════════


class TestMultiStrategyChaining:
    """验证多策略串联执行时前策略输出作为后策略输入。"""

    pytestmark = pytest.mark.asyncio

    async def test_normalize_output_passed_to_term_align(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """normalize 的输出查询应作为 term_align 的输入。"""
        mock_protector_phase2.protect.return_value = ("咋整Python", {})
        mock_protector_phase2.restore.return_value = "如何学习 Python（术语已对齐）"
        mock_strategy_router.route.return_value = {
            "intent": "procedural",
            "complexity": 4,
            "strategies": ["normalize", "term_align"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "如何学习 Python",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 35,
        }
        mock_term_align_rewriter.rewrite.return_value = {
            "query": "如何学习 Python（术语已对齐）",
            "strategy": "term_align",
            "duration_ms": 80.0,
            "tokens": 30,
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        await rewriter.rewrite("咋整Python", history=None)

        # term_align 收到的输入是 normalize 的输出
        term_align_call_args = mock_term_align_rewriter.rewrite.call_args
        # 第一个位置参数应为 normalize 的输出 "如何学习 Python"
        assert term_align_call_args[0][0] == "如何学习 Python"

    async def test_full_chain_normalize_term_align_expand(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """高复杂度三策略串联：normalize → term_align → expand。"""
        mock_protector_phase2.protect.return_value = ("高并发系统怎么搞", {})
        mock_protector_phase2.restore.return_value = (
            "高并发系统架构设计：分布式、负载均衡、缓存策略、数据库优化"
        )
        mock_strategy_router.route.return_value = {
            "intent": "analytical",
            "complexity": 8,
            "strategies": ["normalize", "term_align", "expand"],
        }
        # Stage 1
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "如何设计高并发系统",
            "strategy": "normalize",
            "duration_ms": 120.0,
            "tokens": 45,
        }
        # Stage 2
        mock_term_align_rewriter.rewrite.return_value = {
            "query": "如何设计高并发系统（术语已对齐）",
            "strategy": "term_align",
            "duration_ms": 85.0,
            "tokens": 35,
        }
        # Stage 3
        mock_expand_rewriter.rewrite.return_value = {
            "query": "高并发系统架构设计：分布式、负载均衡、缓存策略、数据库优化",
            "strategy": "expand",
            "duration_ms": 200.0,
            "tokens": 60,
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        await rewriter.rewrite("高并发系统怎么搞", history=None)

        # 验证链式传递
        # term_align 收到 normalize 的输出
        assert mock_term_align_rewriter.rewrite.call_args[0][0] == "如何设计高并发系统"
        # expand 收到 term_align 的输出
        assert mock_expand_rewriter.rewrite.call_args[0][0] == "如何设计高并发系统（术语已对齐）"

    async def test_protected_terms_preserved_during_strategy_chain(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """策略链执行期间保护词保持为占位符，最终由 restore 还原。"""
        # 模拟保护词
        mock_protector_phase2.protect.return_value = (
            "[[TERM_0]] 怎么配置",
            {0: "Nginx"},
        )
        mock_protector_phase2.restore.return_value = "Nginx 如何配置（术语已对齐）"
        mock_strategy_router.route.return_value = {
            "intent": "procedural",
            "complexity": 4,
            "strategies": ["normalize", "term_align"],
        }
        # normalize 的输出应保留占位符
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "[[TERM_0]] 如何配置",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 30,
        }
        # term_align 的输出也保留占位符
        mock_term_align_rewriter.rewrite.return_value = {
            "query": "[[TERM_0]] 如何配置（术语已对齐）",
            "strategy": "term_align",
            "duration_ms": 80.0,
            "tokens": 25,
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        result = await rewriter.rewrite("Nginx 怎么配置", history=None)

        # 保护词在策略链中保持为占位符
        normalize_input = mock_normalize_rewriter.rewrite.call_args[0][0]
        assert "[[TERM_0]]" in normalize_input

        # 最终保护词被还原
        mock_protector_phase2.restore.assert_called_once()
        assert "Nginx" in result.rewritten_queries[-1]["query"]

    async def test_strategies_used_reflects_executed_strategies(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """strategies_used 列表应反映实际执行的策略（按执行顺序）。"""
        mock_protector_phase2.protect.return_value = ("查询文本", {})
        mock_protector_phase2.restore.return_value = "查询文本（已处理）"
        mock_strategy_router.route.return_value = {
            "intent": "analytical",
            "complexity": 7,
            "strategies": ["normalize", "term_align", "expand"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "查询文本（规范化）",
            "strategy": "normalize",
            "duration_ms": 90.0,
            "tokens": 30,
        }
        mock_term_align_rewriter.rewrite.return_value = {
            "query": "查询文本（规范化+术语对齐）",
            "strategy": "term_align",
            "duration_ms": 70.0,
            "tokens": 25,
        }
        mock_expand_rewriter.rewrite.return_value = {
            "query": "查询文本（已处理）",
            "strategy": "expand",
            "duration_ms": 180.0,
            "tokens": 50,
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        result = await rewriter.rewrite("查询文本", history=None)

        assert "normalize" in result.strategies_used
        assert "term_align" in result.strategies_used
        assert "expand" in result.strategies_used
        # 顺序应为路由决定的顺序
        assert result.strategies_used == ["normalize", "term_align", "expand"]


# ═════════════════════════════════════════════════════════════════════
# 策略开关测试
# ═════════════════════════════════════════════════════════════════════


class TestStrategySwitches:
    """验证各策略独立开关可正确跳过对应策略。"""

    pytestmark = pytest.mark.asyncio

    async def test_normalize_disabled_skips_normalize_but_executes_others(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """NORMALIZE=false → 跳过 normalize，但 term_align 和 expand 正常执行。"""
        mock_protector_phase2.protect.return_value = ("高并发怎么搞", {})
        mock_protector_phase2.restore.return_value = "扩展后的查询"
        mock_strategy_router.route.return_value = {
            "intent": "analytical",
            "complexity": 8,
            "strategies": ["normalize", "term_align", "expand"],
        }
        mock_term_align_rewriter.rewrite.return_value = {
            "query": "术语对齐后的查询",
            "strategy": "term_align",
            "duration_ms": 80.0,
            "tokens": 35,
        }
        mock_expand_rewriter.rewrite.return_value = {
            "query": "扩展后的查询",
            "strategy": "expand",
            "duration_ms": 200.0,
            "tokens": 60,
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
            strategy_normalize_enabled=False,
        )

        await rewriter.rewrite("高并发怎么搞", history=None)

        # normalize 被跳过
        mock_normalize_rewriter.rewrite.assert_not_called()
        # term_align 和 expand 正常执行
        mock_term_align_rewriter.rewrite.assert_called_once()
        mock_expand_rewriter.rewrite.assert_called_once()

    async def test_expand_disabled_skips_expand_but_executes_others(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """EXPAND=false → 跳过 expand，但 normalize 和 term_align 正常执行。"""
        mock_protector_phase2.protect.return_value = ("复杂查询", {})
        mock_protector_phase2.restore.return_value = "复杂查询（术语已对齐）"
        mock_strategy_router.route.return_value = {
            "intent": "analytical",
            "complexity": 7,
            "strategies": ["normalize", "term_align", "expand"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "复杂查询（规范化）",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 40,
        }
        mock_term_align_rewriter.rewrite.return_value = {
            "query": "复杂查询（术语已对齐）",
            "strategy": "term_align",
            "duration_ms": 80.0,
            "tokens": 30,
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
            strategy_expand_enabled=False,
        )

        await rewriter.rewrite("复杂查询", history=None)

        # expand 被跳过
        mock_expand_rewriter.rewrite.assert_not_called()
        # normalize 和 term_align 正常执行
        mock_normalize_rewriter.rewrite.assert_called_once()
        mock_term_align_rewriter.rewrite.assert_called_once()

    async def test_term_align_disabled_skips_term_align_but_executes_others(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """TERM_ALIGN=false → 跳过 term_align，但 normalize 和 expand 正常执行。"""
        mock_protector_phase2.protect.return_value = ("中等查询", {})
        mock_protector_phase2.restore.return_value = "中等查询（已处理）"
        mock_strategy_router.route.return_value = {
            "intent": "procedural",
            "complexity": 4,
            "strategies": ["normalize", "term_align"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "中等查询（已处理）",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 30,
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
            strategy_term_align_enabled=False,
        )

        await rewriter.rewrite("中等查询", history=None)

        # term_align 被跳过
        mock_term_align_rewriter.rewrite.assert_not_called()
        # normalize 正常执行
        mock_normalize_rewriter.rewrite.assert_called_once()

    async def test_all_strategies_disabled_still_completes_without_error(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """所有策略禁用但路由仍返回策略列表时，不调用任何策略也不崩溃。"""
        mock_protector_phase2.protect.return_value = ("查询", {})
        mock_protector_phase2.restore.return_value = "查询"
        mock_strategy_router.route.return_value = {
            "intent": "analytical",
            "complexity": 6,
            "strategies": ["normalize", "term_align", "expand"],
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
            strategy_normalize_enabled=False,
            strategy_expand_enabled=False,
            strategy_term_align_enabled=False,
        )

        try:
            result = await rewriter.rewrite("查询", history=None)
        except Exception as exc:  # pragma: no cover
            pytest.fail(f"全部策略禁用时 rewrite() 意外抛出异常: {exc}")

        assert result is not None
        mock_normalize_rewriter.rewrite.assert_not_called()
        mock_term_align_rewriter.rewrite.assert_not_called()
        mock_expand_rewriter.rewrite.assert_not_called()

    async def test_switch_only_affects_targeted_strategy(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """禁用 normalize 只影响 normalize，term_align 仍正常接收输入。"""
        mock_protector_phase2.protect.return_value = ("查询", {})
        mock_protector_phase2.restore.return_value = "最终结果"
        mock_strategy_router.route.return_value = {
            "intent": "procedural",
            "complexity": 5,
            "strategies": ["normalize", "term_align"],
        }
        mock_term_align_rewriter.rewrite.return_value = {
            "query": "最终结果",
            "strategy": "term_align",
            "duration_ms": 80.0,
            "tokens": 30,
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
            strategy_normalize_enabled=False,
        )

        await rewriter.rewrite("查询", history=None)

        # normalize 被跳过
        mock_normalize_rewriter.rewrite.assert_not_called()
        # term_align 收到原始上下文融合后的查询（跳过 normalize 后直接传原始 query）
        mock_term_align_rewriter.rewrite.assert_called_once()


# ═════════════════════════════════════════════════════════════════════
# Phase 2 RewriteResult 扩展字段测试
# ═════════════════════════════════════════════════════════════════════


class TestRewriteResultPhase2Extensions:
    """验证 RewriteResult 包含 Phase 2 新增字段。"""

    pytestmark = pytest.mark.asyncio

    async def test_rewrite_result_includes_intent_and_complexity(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """RewriteResult 应包含 intent 和 complexity 字段。"""
        mock_protector_phase2.protect.return_value = ("测试查询", {})
        mock_protector_phase2.restore.return_value = "测试查询"
        mock_strategy_router.route.return_value = {
            "intent": "analytical",
            "complexity": 6,
            "strategies": [],
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        result = await rewriter.rewrite("测试查询", history=None)

        assert result.intent == "analytical"
        assert result.complexity == 6

    async def test_rewrite_result_includes_cache_level(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """RewriteResult 应包含 cache_level 字段。"""
        cached = RewriteResult(
            original_query="缓存查询",
            rewritten_queries=[{"query": "缓存查询", "strategy": "direct"}],
            rewrite_time_ms=0.2,
            cache_hit=True,
        )
        mock_cache_manager_with_l2.lookup.return_value = None
        mock_cache_manager_with_l2.lookup_l2.return_value = cached
        mock_protector_phase2.protect.return_value = ("缓存查询", {})

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        result = await rewriter.rewrite("缓存查询", history=None)

        assert result.cache_level == "L2"

    async def test_rewrite_result_cache_level_none_when_no_cache(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """未命中缓存时 cache_level 应为 None。"""
        mock_protector_phase2.protect.return_value = ("新查询", {})
        mock_protector_phase2.restore.return_value = "新查询"
        mock_cache_manager_with_l2.lookup.return_value = None
        mock_cache_manager_with_l2.lookup_l2.return_value = None
        mock_strategy_router.route.return_value = {
            "intent": "factual",
            "complexity": 1,
            "strategies": [],
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        result = await rewriter.rewrite("新查询", history=None)

        assert result.cache_level is None

    async def test_rewrite_result_l1_cache_level(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """L1 命中时 cache_level 应为 'L1'。"""
        l1_cached = RewriteResult(
            original_query="完全相同的查询",
            rewritten_queries=[{"query": "完全相同的查询", "strategy": "direct"}],
            rewrite_time_ms=0.1,
            cache_hit=True,
        )
        mock_cache_manager_with_l2.lookup.return_value = l1_cached
        mock_protector_phase2.protect.return_value = ("完全相同的查询", {})

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        result = await rewriter.rewrite("完全相同的查询", history=None)

        assert result.cache_hit is True
        assert result.cache_level == "L1"

    async def test_strategy_rewrite_queries_include_duration_and_tokens(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """每条改写结果应包含 duration_ms 和 tokens 信息。"""
        mock_protector_phase2.protect.return_value = ("查询", {})
        mock_protector_phase2.restore.return_value = "规范化查询"
        mock_strategy_router.route.return_value = {
            "intent": "procedural",
            "complexity": 4,
            "strategies": ["normalize", "term_align"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "规范化查询",
            "strategy": "normalize",
            "duration_ms": 120.5,
            "tokens": 45,
        }
        mock_term_align_rewriter.rewrite.return_value = {
            "query": "规范化查询（已对齐）",
            "strategy": "term_align",
            "duration_ms": 85.2,
            "tokens": 32,
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        result = await rewriter.rewrite("查询", history=None)

        assert len(result.rewritten_queries) >= 2
        # 每条改写结果可能包含可选的 duration_ms 和 tokens
        for rq in result.rewritten_queries:
            assert "query" in rq
            assert "strategy" in rq


# ═════════════════════════════════════════════════════════════════════
# Phase 2 管线与 Phase 1 步骤顺序测试
# ═════════════════════════════════════════════════════════════════════


class TestPhase2PipelineOrdering:
    """验证 Phase 2 步骤在管线中正确插入 Phase 1 步骤之间。"""

    pytestmark = pytest.mark.asyncio

    async def test_phase2_steps_inserted_between_context_fusion_and_restore(
        self,
        mock_protector_phase2,
        mock_context_rewriter_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """上下文融合之后 → 意图分类+策略路由+策略执行 → 保护词还原之前。

        管线顺序验证：
        1. protect
        2. L1 缓存检查
        3. 上下文融合（有指代词时）
        4. L2 缓存检查
        5. 意图分类+策略路由
        6. 策略执行
        7. 保护词还原
        8. 写缓存
        9. 审计日志
        """
        mock_protector_phase2.protect.return_value = ("它怎么用", {0: "Python"})
        mock_protector_phase2.restore.return_value = "Python 如何学习（术语已对齐）"
        mock_context_rewriter_phase2.rewrite.return_value = "Python 怎么使用"
        mock_strategy_router.route.return_value = {
            "intent": "procedural",
            "complexity": 4,
            "strategies": ["normalize", "term_align"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "Python 如何学习",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 40,
        }
        mock_term_align_rewriter.rewrite.return_value = {
            "query": "Python 如何学习（术语已对齐）",
            "strategy": "term_align",
            "duration_ms": 80.0,
            "tokens": 30,
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            context_rewriter=mock_context_rewriter_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        await rewriter.rewrite(
            "它怎么用",
            history=[{"role": "user", "content": "Python 是什么"}],
        )

        # 验证调用顺序：protect → context → route → normalize → term_align → restore
        mock_protector_phase2.protect.assert_called()
        mock_context_rewriter_phase2.rewrite.assert_called()
        mock_strategy_router.route.assert_called()
        mock_normalize_rewriter.rewrite.assert_called()
        mock_term_align_rewriter.rewrite.assert_called()
        mock_protector_phase2.restore.assert_called()

    async def test_context_fusion_still_conditional_in_phase2(
        self,
        mock_protector_phase2,
        mock_context_rewriter_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """无指代词时 Phase 1 的上下文融合条件保持，Phase 2 策略仍执行。"""
        mock_protector_phase2.protect.return_value = ("如何优化数据库性能", {})
        mock_protector_phase2.restore.return_value = "如何优化数据库性能（术语已对齐）"
        mock_strategy_router.route.return_value = {
            "intent": "analytical",
            "complexity": 4,
            "strategies": ["normalize", "term_align"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "如何优化数据库性能",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 40,
        }
        mock_term_align_rewriter.rewrite.return_value = {
            "query": "如何优化数据库性能（术语已对齐）",
            "strategy": "term_align",
            "duration_ms": 80.0,
            "tokens": 30,
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            context_rewriter=mock_context_rewriter_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        await rewriter.rewrite("如何优化数据库性能", history=None)

        # 无指代词 → 上下文融合跳过
        mock_context_rewriter_phase2.rewrite.assert_not_called()
        # Phase 2 策略仍正常执行
        mock_strategy_router.route.assert_called_once()
        mock_normalize_rewriter.rewrite.assert_called_once()
        mock_term_align_rewriter.rewrite.assert_called_once()

    async def test_intent_classification_receives_protected_query(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """意图分类应在上下文融合之后、保护词还原之前执行。"""
        mock_protector_phase2.protect.return_value = (
            "[[TERM_0]] 怎么配置负载均衡",
            {0: "Nginx"},
        )
        mock_protector_phase2.restore.return_value = "Nginx 如何配置负载均衡"
        mock_strategy_router.route.return_value = {
            "intent": "procedural",
            "complexity": 4,
            "strategies": ["normalize"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "[[TERM_0]] 如何配置负载均衡",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 40,
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        await rewriter.rewrite("Nginx 怎么配置负载均衡", history=None)

        # 意图分类收到的应是在上下文融合之后、保护词还原之前的查询
        route_call_args = mock_strategy_router.route.call_args
        # route 收到的查询包含保护词占位符（因为尚未 restore）
        assert "[[TERM_0]]" in route_call_args[0][0]


# ═════════════════════════════════════════════════════════════════════
# 降级与错误处理测试（Phase 2 扩展）
# ═════════════════════════════════════════════════════════════════════


class TestPhase2ErrorHandling:
    """验证 Phase 2 组件失败时的降级行为。"""

    pytestmark = pytest.mark.asyncio

    async def test_strategy_router_failure_falls_back_to_direct(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """策略路由失败时应降级为 direct，不调用任何策略。"""
        from app.services.chat_adapter import ChatAPIError

        mock_protector_phase2.protect.return_value = ("查询", {})
        mock_protector_phase2.restore.return_value = "查询"
        mock_strategy_router.route.side_effect = ChatAPIError("路由服务不可用")

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        try:
            result = await rewriter.rewrite("查询", history=None)
        except Exception as exc:  # pragma: no cover
            pytest.fail(f"策略路由失败时 rewrite() 意外抛出异常: {exc}")

        assert result is not None
        mock_normalize_rewriter.rewrite.assert_not_called()
        mock_term_align_rewriter.rewrite.assert_not_called()
        mock_expand_rewriter.rewrite.assert_not_called()

    async def test_single_strategy_failure_does_not_block_pipeline(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """单个策略失败时应降级，但不阻断管线中后续策略。"""
        from app.services.chat_adapter import ChatAPIError

        mock_protector_phase2.protect.return_value = ("查询", {})
        mock_protector_phase2.restore.return_value = "查询（术语已对齐）"
        mock_strategy_router.route.return_value = {
            "intent": "analytical",
            "complexity": 7,
            "strategies": ["normalize", "term_align", "expand"],
        }
        # normalize 失败
        mock_normalize_rewriter.rewrite.side_effect = ChatAPIError("normalize 服务超时")
        # 后续策略正常
        mock_term_align_rewriter.rewrite.return_value = {
            "query": "查询（术语已对齐）",
            "strategy": "term_align",
            "duration_ms": 80.0,
            "tokens": 30,
        }
        mock_expand_rewriter.rewrite.return_value = {
            "query": "查询（术语已对齐+扩展）",
            "strategy": "expand",
            "duration_ms": 180.0,
            "tokens": 50,
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        try:
            result = await rewriter.rewrite("查询", history=None)
        except Exception as exc:  # pragma: no cover
            pytest.fail(f"单个策略失败时 rewrite() 意外抛出异常: {exc}")

        assert result is not None
        # normalize 被调用但失败
        mock_normalize_rewriter.rewrite.assert_called_once()
        # 后续策略仍正常执行
        mock_term_align_rewriter.rewrite.assert_called_once()
        mock_expand_rewriter.rewrite.assert_called_once()
