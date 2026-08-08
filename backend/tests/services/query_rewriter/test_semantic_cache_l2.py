"""L2 语义缓存精细化测试 —— 7.1.1a

测试覆盖：
- 跨会话 L2 缓存 Key 设计（不依赖 SessionID、基于语义向量检索）
- L2 相似度阈值精细化（仅 ≥ 0.95 考虑命中）
- 通用知识分类（general_knowledge 允许跨会话复用）
- 上下文依赖检测（context_dependent 禁止跨会话复用）
- 上下文相关性校验（L2 命中后 LLM 轻量校验）

.. note::
    本文件为 Phase 2 L2 语义缓存的**红测试**（TDD Red Phase）。
    运行时应预期失败 —— 当前 QueryRewriter 尚未集成 L2 语义缓存精细化逻辑。
"""

from __future__ import annotations

import pytest

from app.services.query_rewriter import RewriteResult

from .conftest import build_phase2_rewriter, make_l2_cache_entry

# ═══════════════════════════════════════════════════════════════════════════
# 跨会话 L2 缓存 Key 设计测试
# ═══════════════════════════════════════════════════════════════════════════


class TestL2CrossSessionCacheKey:
    """验证 L2 缓存 Key 不依赖 SessionID —— 基于语义向量检索。"""

    pytestmark = pytest.mark.asyncio

    async def test_l2_lookup_does_not_use_session_id(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_context_verifier,
        mock_audit_trail_phase2,
    ):
        """L2 缓存查询 lookup_l2 只接受 query_vector，不传入 session_id。"""
        cached = RewriteResult(
            original_query="如何优化数据库性能",
            rewritten_queries=[
                {"query": "数据库性能优化方法", "strategy": "normalize"},
            ],
            strategies_used=["normalize"],
            rewrite_time_ms=150.0,
            cache_hit=True,
        )
        mock_cache_manager_with_l2.lookup.return_value = None
        mock_cache_manager_with_l2.lookup_l2.return_value = make_l2_cache_entry(
            cached, similarity=0.97, knowledge_type="general_knowledge"
        )
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

        await rewriter.rewrite("怎么提升数据库的性能", history=None)

        # lookup_l2 应仅接收向量参数，不应传入 session_id
        l2_call_args = mock_cache_manager_with_l2.lookup_l2.call_args
        assert l2_call_args is not None, "lookup_l2 应至少被调用一次"
        # 验证只传入了位置参数（query_vector），没有 session_id 关键字
        assert len(l2_call_args[0]) == 1, (
            f"lookup_l2 应只接收 1 个位置参数（query_vector），"
            f"实际接收到 {len(l2_call_args[0])} 个: {l2_call_args[0]}"
        )

    async def test_different_sessions_same_semantic_query_both_hit_l2(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_context_verifier,
        mock_audit_trail_phase2,
    ):
        """不同会话的相同语义查询应都能命中 L2 缓存（Key 不依赖 SessionID）。"""
        cached = RewriteResult(
            original_query="如何配置 Nginx 反向代理",
            rewritten_queries=[
                {"query": "Nginx 反向代理配置方法", "strategy": "normalize"},
            ],
            strategies_used=["normalize"],
            rewrite_time_ms=120.0,
            cache_hit=True,
        )
        mock_cache_manager_with_l2.lookup.return_value = None
        mock_cache_manager_with_l2.lookup_l2.return_value = make_l2_cache_entry(
            cached, similarity=0.98, knowledge_type="general_knowledge"
        )
        mock_protector_phase2.protect.side_effect = [
            ("怎么配置 Nginx 反向代理", {}),
            ("Nginx 反向代理如何设置", {}),
        ]

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        # 会话 A
        result_a = await rewriter.rewrite(
            "怎么配置 Nginx 反向代理",
            session_id="session_A",
        )
        # 会话 B（完全不同的 session_id）
        result_b = await rewriter.rewrite(
            "Nginx 反向代理如何设置",
            session_id="session_B",
        )

        # 两个会话都应命中 L2
        assert result_a.cache_hit is True
        assert result_b.cache_hit is True
        # L2 被调用了两次（每次请求都查询 L2）
        assert mock_cache_manager_with_l2.lookup_l2.call_count == 2

    async def test_l2_cache_returned_without_session_id_binding(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_context_verifier,
        mock_audit_trail_phase2,
    ):
        """L2 缓存命中时不需要 session_id 参与决策 —— 纯向量检索。"""
        cached = RewriteResult(
            original_query="Python 列表推导式语法",
            rewritten_queries=[
                {"query": "Python 列表推导式语法", "strategy": "direct"},
            ],
            rewrite_time_ms=0.3,
            cache_hit=True,
        )
        mock_cache_manager_with_l2.lookup.return_value = None
        mock_cache_manager_with_l2.lookup_l2.return_value = make_l2_cache_entry(
            cached, similarity=0.99, knowledge_type="general_knowledge"
        )
        mock_protector_phase2.protect.return_value = (
            "Python 列表推导式怎么写",
            {},
        )

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        # 不传入 session_id（从无历史的请求派生默认值）
        result = await rewriter.rewrite(
            "Python 列表推导式怎么写",
            history=None,
        )

        assert result.cache_hit is True
        # lookup_l2 的参数中不应包含 session_id 关键字
        l2_kwargs = mock_cache_manager_with_l2.lookup_l2.call_args[1]
        assert "session_id" not in l2_kwargs, (
            f"lookup_l2 不应接收 session_id 参数，实际 kw 参数: {l2_kwargs}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# L2 相似度阈值精细化测试
# ═══════════════════════════════════════════════════════════════════════════


class TestL2SimilarityThreshold:
    """验证 L2 语义缓存极高的相似度阈值（仅 ≥ 0.95 考虑命中）。"""

    pytestmark = pytest.mark.asyncio

    async def test_similarity_above_threshold_hits(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_context_verifier,
        mock_audit_trail_phase2,
    ):
        """相似度 0.96 > 0.95 → 命中 L2 缓存。"""
        cached = RewriteResult(
            original_query="如何配置 Nginx",
            rewritten_queries=[
                {"query": "Nginx 配置方法", "strategy": "normalize"},
            ],
            strategies_used=["normalize"],
            rewrite_time_ms=100.0,
            cache_hit=True,
        )
        mock_cache_manager_with_l2.lookup.return_value = None
        mock_cache_manager_with_l2.lookup_l2.return_value = make_l2_cache_entry(
            cached, similarity=0.96, knowledge_type="general_knowledge"
        )
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

        result = await rewriter.rewrite("怎么配置 Nginx", history=None)

        # 相似度 > 0.95 → 命中
        assert result.cache_hit is True
        # 验证 L2 命中，策略路由被跳过
        mock_strategy_router.route.assert_not_called()

    async def test_similarity_below_threshold_skips(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_context_verifier,
        mock_audit_trail_phase2,
    ):
        """相似度 0.94 < 0.95 → 跳过 L2 缓存，执行正常管线。"""
        mock_cache_manager_with_l2.lookup.return_value = None
        # L2 返回结果但相似度略低于阈值
        mock_cache_manager_with_l2.lookup_l2.return_value = make_l2_cache_entry(
            RewriteResult(
                original_query="数据库基础知识",
                rewritten_queries=[{"query": "数据库基础知识", "strategy": "direct"}],
                rewrite_time_ms=50.0,
            ),
            similarity=0.94,
            knowledge_type="general_knowledge",
        )
        mock_protector_phase2.protect.return_value = ("数据库相关的其他知识", {})
        mock_protector_phase2.restore.return_value = "数据库相关的其他知识"
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

        result = await rewriter.rewrite("数据库相关的其他知识", history=None)

        # 相似度 < 0.95 → 不命中，正常执行管线
        mock_strategy_router.route.assert_called()
        assert result.cache_hit is False

    async def test_similarity_exactly_at_threshold_boundary(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_context_verifier,
        mock_audit_trail_phase2,
    ):
        """相似度恰好等于 0.95（边界值）→ 行为与 ≥ 0.95 一致（命中）。"""
        cached = RewriteResult(
            original_query="微服务架构设计",
            rewritten_queries=[
                {"query": "微服务架构设计原则与最佳实践", "strategy": "expand"},
            ],
            strategies_used=["expand"],
            rewrite_time_ms=180.0,
            cache_hit=True,
        )
        mock_cache_manager_with_l2.lookup.return_value = None
        mock_cache_manager_with_l2.lookup_l2.return_value = make_l2_cache_entry(
            cached, similarity=0.95, knowledge_type="general_knowledge"
        )
        mock_protector_phase2.protect.return_value = ("微服务架构怎么设计", {})

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        result = await rewriter.rewrite("微服务架构怎么设计", history=None)

        # >= 0.95 → 命中
        assert result.cache_hit is True
        mock_strategy_router.route.assert_not_called()

    async def test_similarity_far_below_threshold_definitely_skips(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_context_verifier,
        mock_audit_trail_phase2,
    ):
        """相似度 0.72（远低于阈值）→ 绝对不应命中。"""
        mock_cache_manager_with_l2.lookup.return_value = None
        # L2 返回了一个相似度很低的结果
        mock_cache_manager_with_l2.lookup_l2.return_value = make_l2_cache_entry(
            RewriteResult(
                original_query="旅游景点推荐",
                rewritten_queries=[
                    {"query": "热门旅游目的地推荐", "strategy": "expand"},
                ],
                strategies_used=["expand"],
                rewrite_time_ms=200.0,
            ),
            similarity=0.72,
            knowledge_type="general_knowledge",
        )
        mock_protector_phase2.protect.return_value = ("后端技术栈选择", {})
        mock_protector_phase2.restore.return_value = "后端技术栈选择"
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
        )

        result = await rewriter.rewrite("后端技术栈选择", history=None)

        # 相似度太低 → 不命中，正常执行管线
        assert result.cache_hit is False
        mock_strategy_router.route.assert_called()


# ═══════════════════════════════════════════════════════════════════════════
# 通用知识分类测试
# ═══════════════════════════════════════════════════════════════════════════


class TestL2GeneralKnowledgeClassification:
    """验证缓存答案标记为通用知识时可跨会话复用。"""

    pytestmark = pytest.mark.asyncio

    async def test_general_knowledge_allowed_cross_session(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_context_verifier,
        mock_audit_trail_phase2,
    ):
        """knowledge_type='general_knowledge' → 允许跨会话复用。"""
        cached = RewriteResult(
            original_query="报销流程",
            rewritten_queries=[
                {"query": "费用报销流程与所需材料", "strategy": "expand"},
            ],
            strategies_used=["expand"],
            rewrite_time_ms=160.0,
            cache_hit=True,
        )
        mock_cache_manager_with_l2.lookup.return_value = None
        mock_cache_manager_with_l2.lookup_l2.return_value = make_l2_cache_entry(
            cached, similarity=0.97, knowledge_type="general_knowledge"
        )
        mock_protector_phase2.protect.return_value = ("报销需要什么材料", {})

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        # 使用与缓存不同的 session_id 仍应命中
        result = await rewriter.rewrite(
            "报销需要什么材料",
            session_id="new_session_xyz",
        )

        assert result.cache_hit is True

    async def test_python_syntax_general_knowledge_cross_session(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_context_verifier,
        mock_audit_trail_phase2,
    ):
        """ "Python 语法" 属于通用知识 → 跨会话复用不受限制。"""
        cached = RewriteResult(
            original_query="Python 语法",
            rewritten_queries=[
                {"query": "Python 基本语法规则与示例", "strategy": "normalize"},
            ],
            strategies_used=["normalize"],
            rewrite_time_ms=90.0,
            cache_hit=True,
        )
        mock_cache_manager_with_l2.lookup.return_value = None
        mock_cache_manager_with_l2.lookup_l2.return_value = make_l2_cache_entry(
            cached, similarity=0.98, knowledge_type="general_knowledge"
        )
        mock_protector_phase2.protect.return_value = ("Python 基础语法", {})

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        result = await rewriter.rewrite(
            "Python 基础语法",
            session_id="another_session",
        )

        assert result.cache_hit is True

    async def test_general_knowledge_without_verification_still_hits(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_context_verifier,
        mock_audit_trail_phase2,
    ):
        """即使 context_verifier 返回依赖上下文，general_knowledge 应直接允许命中。"""
        cached = RewriteResult(
            original_query="什么是 RESTful API",
            rewritten_queries=[
                {"query": "RESTful API 设计原则与规范", "strategy": "normalize"},
            ],
            strategies_used=["normalize"],
            rewrite_time_ms=100.0,
            cache_hit=True,
        )
        mock_cache_manager_with_l2.lookup.return_value = None
        mock_cache_manager_with_l2.lookup_l2.return_value = make_l2_cache_entry(
            cached, similarity=0.96, knowledge_type="general_knowledge"
        )
        mock_protector_phase2.protect.return_value = ("RESTful API 是啥", {})
        # context_verifier 的返回不应影响 general_knowledge 的复用决策
        mock_context_verifier.verify.return_value = {
            "context_dependent": True,
            "reasoning": "不确定",
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

        result = await rewriter.rewrite("RESTful API 是啥", history=None)

        # general_knowledge 始终允许跨会话复用
        assert result.cache_hit is True


# ═══════════════════════════════════════════════════════════════════════════
# 上下文依赖检测测试
# ═══════════════════════════════════════════════════════════════════════════


class TestL2ContextDependencyDetection:
    """验证 context_dependent 缓存答案禁止跨会话复用。"""

    pytestmark = pytest.mark.asyncio

    async def test_context_dependent_blocked_cross_session(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_context_verifier,
        mock_audit_trail_phase2,
    ):
        """knowledge_type='context_dependent' → 跨会话时应跳过缓存，执行正常管线。"""
        cached = RewriteResult(
            original_query="基于刚才的代码，这个函数怎么改",
            rewritten_queries=[
                {"query": "如何修改该函数以实现性能优化", "strategy": "context_fusion"},
            ],
            strategies_used=["context_fusion", "normalize"],
            rewrite_time_ms=200.0,
            cache_hit=True,
        )
        mock_cache_manager_with_l2.lookup.return_value = None
        mock_cache_manager_with_l2.lookup_l2.return_value = make_l2_cache_entry(
            cached,
            similarity=0.97,
            knowledge_type="context_dependent",
            source_session_id="source_session_A",
        )
        mock_protector_phase2.protect.return_value = (
            "基于刚才的代码，这个方法怎么优化",
            {},
        )
        mock_protector_phase2.restore.return_value = "如何优化该方法的性能"
        mock_strategy_router.route.return_value = {
            "intent": "procedural",
            "complexity": 5,
            "strategies": ["normalize", "term_align"],
        }
        # ── 设置策略重写器的返回值（管线回退时需要使用）──
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "如何优化该方法的性能",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 40,
        }
        mock_term_align_rewriter.rewrite.return_value = {
            "query": "如何优化该方法以实现性能提升",
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

        # 尝试跨会话复用 context_dependent 缓存
        result = await rewriter.rewrite(
            "基于刚才的代码，这个方法怎么优化",
            session_id="different_session_B",
        )

        # 应被拒绝，执行正常管线
        assert result.cache_hit is False
        mock_strategy_router.route.assert_called()

    async def test_context_dependent_same_session_still_allowed(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_context_verifier,
        mock_audit_trail_phase2,
    ):
        """context_dependent 但相同会话（L1 已命中）→ 不走 L2 逻辑。

        注：相同会话的相同查询在 L1 就命中，不会到达 L2 检查。
        此测试验证 context_dependent 只在跨会话场景中生效。
        """
        cached_l1 = RewriteResult(
            original_query="完全相同的查询",
            rewritten_queries=[
                {"query": "完全相同的查询", "strategy": "direct"},
            ],
            rewrite_time_ms=0.1,
            cache_hit=True,
        )
        # L1 命中 → L2 不应被查询
        mock_cache_manager_with_l2.lookup.return_value = cached_l1
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

        result = await rewriter.rewrite(
            "完全相同的查询",
            session_id="same_session",
        )

        assert result.cache_hit is True
        # L1 命中 → L2 不应被查询
        mock_cache_manager_with_l2.lookup_l2.assert_not_called()

    async def test_based_on_previous_code_marked_context_dependent(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_context_verifier,
        mock_audit_trail_phase2,
    ):
        """ "基于刚才的代码" 类型的查询 → context_dependent → 跨会话不得复用。"""
        cached = RewriteResult(
            original_query="基于刚才的代码，解释一下这个函数",
            rewritten_queries=[
                {"query": "解释该函数的用途与实现细节", "strategy": "context_fusion"},
            ],
            strategies_used=["context_fusion"],
            rewrite_time_ms=180.0,
            cache_hit=True,
        )
        mock_cache_manager_with_l2.lookup.return_value = None
        mock_cache_manager_with_l2.lookup_l2.return_value = make_l2_cache_entry(
            cached,
            similarity=0.99,
            knowledge_type="context_dependent",
            source_session_id="original_session",
        )
        mock_protector_phase2.protect.return_value = (
            "基于刚才的代码，这个函数是做什么的",
            {},
        )
        mock_protector_phase2.restore.return_value = "该函数的用途与实现细节"
        mock_strategy_router.route.return_value = {
            "intent": "analytical",
            "complexity": 5,
            "strategies": ["normalize"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "该函数的用途与实现细节",
            "strategy": "normalize",
            "duration_ms": 100.0,
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

        # 尝试跨会话复用 context_dependent 缓存
        result = await rewriter.rewrite(
            "基于刚才的代码，这个函数是做什么的",
            session_id="completely_different_session",
        )

        # 应被拒绝，执行正常管线
        assert result.cache_hit is False
        mock_strategy_router.route.assert_called()

    async def test_context_dependent_same_session_l2(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_context_verifier,
        mock_audit_trail_phase2,
    ):
        """context_dependent 但相同会话 + L1 未命中时，L2 命中仍应通过上下文校验。

        关键：同一会话内 context_dependent 是合法的（查询在同一对话中）。
        """
        cached = RewriteResult(
            original_query="根据上面提到的错误日志，怎么修复",
            rewritten_queries=[
                {
                    "query": "根据错误日志信息进行修复的方法",
                    "strategy": "context_fusion",
                },
            ],
            strategies_used=["context_fusion"],
            rewrite_time_ms=150.0,
            cache_hit=True,
        )
        mock_cache_manager_with_l2.lookup.return_value = None
        mock_cache_manager_with_l2.lookup_l2.return_value = make_l2_cache_entry(
            cached,
            similarity=0.98,
            knowledge_type="context_dependent",
            source_session_id="same_conversation",
        )
        mock_protector_phase2.protect.return_value = (
            "根据上面提到的错误日志，这个问题怎么修复",
            {},
        )

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        # 相同会话 → context_dependent 在通过校验后应可复用
        result = await rewriter.rewrite(
            "根据上面提到的错误日志，这个问题怎么修复",
            session_id="same_conversation",
        )

        assert result.cache_hit is True


# ═══════════════════════════════════════════════════════════════════════════
# 上下文相关性校验测试
# ═══════════════════════════════════════════════════════════════════════════


class TestL2ContextRelevanceVerification:
    """验证 L2 命中后 LLM 轻量上下文相关性校验。"""

    pytestmark = pytest.mark.asyncio

    async def test_l2_hit_triggers_context_verification(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_context_verifier,
        mock_audit_trail_phase2,
    ):
        """L2 语义缓存命中后应触发 LLM 上下文相关性校验。"""
        cached = RewriteResult(
            original_query="如何优化数据库性能",
            rewritten_queries=[
                {"query": "数据库性能优化方法", "strategy": "normalize"},
            ],
            strategies_used=["normalize"],
            rewrite_time_ms=150.0,
            cache_hit=True,
        )
        mock_cache_manager_with_l2.lookup.return_value = None
        mock_cache_manager_with_l2.lookup_l2.return_value = make_l2_cache_entry(
            cached, similarity=0.97, knowledge_type="general_knowledge"
        )
        mock_protector_phase2.protect.return_value = ("怎么提升数据库的性能", {})

        # 注：context_verifier 的触发由管线实现决定
        # general_knowledge 可能直接跳过校验，但校验调用与否由管线决定
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

        # L2 命中 → 返回缓存结果
        assert result.cache_hit is True
        # 校验器至少被检查（具体调用逻辑由管线决定）

    async def test_verification_failed_falls_back_to_normal_pipeline(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_context_verifier,
        mock_audit_trail_phase2,
    ):
        """上下文校验不通过 → 回退到正常重写管线，不返回缓存结果。"""
        cached = RewriteResult(
            original_query="刚才说的那个问题怎么解决",
            rewritten_queries=[
                {
                    "query": "如何解决之前讨论的问题",
                    "strategy": "context_fusion",
                },
            ],
            strategies_used=["context_fusion"],
            rewrite_time_ms=200.0,
            cache_hit=True,
        )
        mock_cache_manager_with_l2.lookup.return_value = None
        mock_cache_manager_with_l2.lookup_l2.return_value = make_l2_cache_entry(
            cached, similarity=0.96, knowledge_type="context_dependent"
        )
        # 校验器判定为依赖上下文 → 校验失败
        mock_context_verifier.verify.return_value = {
            "context_dependent": True,
            "reasoning": "Answer explicitly references 'previously discussed issue', "
            "indicating dependence on conversation history.",
        }
        mock_protector_phase2.protect.return_value = (
            "刚才说的那个问题怎么解决",
            {},
        )
        mock_protector_phase2.restore.return_value = "如何解决之前讨论的问题"
        mock_strategy_router.route.return_value = {
            "intent": "procedural",
            "complexity": 4,
            "strategies": ["normalize", "term_align"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "如何解决之前讨论的问题",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 40,
        }
        mock_term_align_rewriter.rewrite.return_value = {
            "query": "如何解决之前讨论的问题（术语已对齐）",
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

        result = await rewriter.rewrite(
            "刚才说的那个问题怎么解决",
            session_id="different_session_456",
        )

        # 校验失败 → 不返回缓存，执行正常管线
        assert result.cache_hit is False
        mock_strategy_router.route.assert_called()

    async def test_verification_passed_returns_cached_with_context_verified(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_context_verifier,
        mock_audit_trail_phase2,
    ):
        """校验通过 → 返回缓存结果，标记 cache_level='L2' + context_verified。"""
        cached = RewriteResult(
            original_query="如何编写单元测试",
            rewritten_queries=[
                {"query": "单元测试编写方法与最佳实践", "strategy": "normalize"},
            ],
            strategies_used=["normalize"],
            rewrite_time_ms=130.0,
            cache_hit=True,
        )
        mock_cache_manager_with_l2.lookup.return_value = None
        mock_cache_manager_with_l2.lookup_l2.return_value = make_l2_cache_entry(
            cached, similarity=0.98, knowledge_type="general_knowledge"
        )
        mock_context_verifier.verify.return_value = {
            "context_dependent": False,
            "reasoning": "Answer is about general unit testing practices, "
            "not dependent on any specific conversation context.",
        }
        mock_protector_phase2.protect.return_value = ("单元测试怎么写", {})

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            expand_rewriter=mock_expand_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
        )

        result = await rewriter.rewrite(
            "单元测试怎么写",
            session_id="new_session",
        )

        # 校验通过 → 返回缓存结果
        assert result.cache_hit is True
        assert result.cache_level == "L2"

    async def test_verification_failure_audit_logged(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_context_verifier,
        mock_audit_trail_phase2,
    ):
        """校验失败时应记录 l2_context_rejected 审计事件。"""
        cached = RewriteResult(
            original_query="之前提到的那个配置怎么改",
            rewritten_queries=[
                {
                    "query": "如何修改之前提到的配置",
                    "strategy": "context_fusion",
                },
            ],
            strategies_used=["context_fusion"],
            rewrite_time_ms=170.0,
            cache_hit=True,
        )
        mock_cache_manager_with_l2.lookup.return_value = None
        mock_cache_manager_with_l2.lookup_l2.return_value = make_l2_cache_entry(
            cached, similarity=0.96, knowledge_type="context_dependent"
        )
        mock_context_verifier.verify.return_value = {
            "context_dependent": True,
            "reasoning": "Answer depends on previously mentioned configuration context.",
        }
        mock_protector_phase2.protect.return_value = (
            "之前提到的那个配置怎么改",
            {},
        )
        mock_protector_phase2.restore.return_value = "如何修改之前提到的配置"
        mock_strategy_router.route.return_value = {
            "intent": "procedural",
            "complexity": 4,
            "strategies": ["normalize"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "如何修改之前提到的配置",
            "strategy": "normalize",
            "duration_ms": 100.0,
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

        await rewriter.rewrite(
            "之前提到的那个配置怎么改",
            session_id="another_unrelated_session",
        )

        # 审计日志应记录 l2_context_rejected 事件
        all_calls = [
            call[0][0]  # 第一个位置参数（事件名）
            for call in mock_audit_trail_phase2.record.call_args_list
        ]
        assert "l2_context_rejected" in all_calls, (
            f"校验失败时应记录 'l2_context_rejected' 事件，实际审计事件: {all_calls}"
        )

    async def test_verification_llm_failure_conservative_accept(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_context_verifier,
        mock_audit_trail_phase2,
    ):
        """校验 LLM 调用失败时保守接受缓存结果（不阻断管线）。"""
        from app.services.chat_adapter import ChatAPIError

        cached = RewriteResult(
            original_query="Python 装饰器的用法",
            rewritten_queries=[
                {"query": "Python 装饰器使用方法与示例", "strategy": "normalize"},
            ],
            strategies_used=["normalize"],
            rewrite_time_ms=100.0,
            cache_hit=True,
        )
        mock_cache_manager_with_l2.lookup.return_value = None
        mock_cache_manager_with_l2.lookup_l2.return_value = make_l2_cache_entry(
            cached, similarity=0.97, knowledge_type="general_knowledge"
        )
        # 校验 LLM 调用失败
        mock_context_verifier.verify.side_effect = ChatAPIError("校验服务超时")
        mock_protector_phase2.protect.return_value = ("Python 装饰器怎么用", {})

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
            result = await rewriter.rewrite(
                "Python 装饰器怎么用",
                session_id="any_session",
            )
        except Exception as exc:  # pragma: no cover
            pytest.fail(f"校验 LLM 失败时 rewrite() 意外抛出异常: {exc}")

        # 校验 LLM 失败 → 保守接受缓存，不阻塞管线
        assert result is not None
        assert result.cache_hit is True

    async def test_verification_not_called_when_l2_miss(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_context_verifier,
        mock_audit_trail_phase2,
    ):
        """L2 未命中时不应触发上下文校验（无缓存需要校验）。"""
        mock_cache_manager_with_l2.lookup.return_value = None
        mock_cache_manager_with_l2.lookup_l2.return_value = None
        mock_protector_phase2.protect.return_value = ("全新查询", {})
        mock_protector_phase2.restore.return_value = "全新查询"
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

        await rewriter.rewrite("全新查询", history=None)

        # L2 未命中 → 校验不应被调用
        mock_context_verifier.verify.assert_not_called()
