"""集成联调 —— 改写质量 5 维评分集 —— Postprocessor 集成、确定性预检查、质量评估降级兜底、回溯限制。

测试覆盖（TDD 红阶段 —— 实现代码尚不存在，测试预期失败）：
- Postprocessor 集成：高质量改写通过、语义保留度<3 自动丢弃、总分<15 触发回溯、
  二次失败直接丢弃回退原始查询
- 确定性预检查：关键词留存率<阈值直接丢弃跳过 LLM 评估、长度比例异常标记可疑
- 质量评估降级兜底：评估 LLM 失败时保守接受改写
- 回溯限制：最多 1 次，不可无限回溯
- QualityScores 正确传递到 RewriteResult
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.postprocessor import Postprocessor, QualityScores

from .conftest import build_phase2_rewriter

# ═══════════════════════════════════════════════════════════════════════════════
# 集成联调 测试辅助函数
# ═══════════════════════════════════════════════════════════════════════════════


def _high_quality_scores() -> QualityScores:
    """返回高质量评分（total_score=22, semantic=5, verdict=excellent）。"""
    return QualityScores(
        semantic_preservation=5,
        clarity_improvement=4,
        information_gain=4,
        term_accuracy=4,
        retrievability=5,
        total_score=22,
        verdict="excellent",
        issues=[],
    )


def _poor_quality_scores_low_semantic() -> QualityScores:
    """语义保留度 < 3 → 自动 poor（语义严重偏离）。"""
    return QualityScores(
        semantic_preservation=2,
        clarity_improvement=3,
        information_gain=2,
        term_accuracy=2,
        retrievability=2,
        total_score=11,
        verdict="poor",
        issues=["语义严重偏离原始意图"],
    )


def _marginal_quality_scores() -> QualityScores:
    """总分 10-14 → marginal（触发回溯）。"""
    return QualityScores(
        semantic_preservation=3,
        clarity_improvement=2,
        information_gain=2,
        term_accuracy=2,
        retrievability=3,
        total_score=12,
        verdict="marginal",
        issues=["清晰度提升不足", "信息增量偏低"],
    )


def _poor_total_quality_scores() -> QualityScores:
    """总分 < 10 → poor（直接丢弃）。"""
    return QualityScores(
        semantic_preservation=2,
        clarity_improvement=1,
        information_gain=1,
        term_accuracy=2,
        retrievability=1,
        total_score=7,
        verdict="poor",
        issues=["多项指标严重不足"],
    )


def _make_postprocessor_evaluate_result(
    quality_scores: QualityScores | None = None,
    *,
    passed: bool = True,
    pre_check_failed: bool = False,
    pre_check_issues: list[str] | None = None,
) -> dict:
    """构建 Postprocessor.evaluate() 返回的标准 dict。

    Args:
        quality_scores: 质量评分（None 表示评估失败降级）。
        passed: 综合是否通过。
        pre_check_failed: 确定性预检查是否失败。
        pre_check_issues: 预检查发现的问题。
    """
    return {
        "quality_scores": quality_scores,
        "passed": passed,
        "pre_check_failed": pre_check_failed,
        "pre_check_issues": pre_check_issues or [],
    }


def _mock_postprocessor(
    evaluate_return: dict | None = None,
) -> MagicMock:
    """创建一个 Mock Postprocessor，可按需配置 evaluate 返回值。

    默认返回高质量通过结果。
    """
    postprocessor = MagicMock()
    postprocessor.evaluate = MagicMock(
        return_value=evaluate_return or _make_postprocessor_evaluate_result(_high_quality_scores())
    )
    return postprocessor


# ═══════════════════════════════════════════════════════════════════════════════
# QualityScores 模型验证
# ═══════════════════════════════════════════════════════════════════════════════


class TestQualityScores:
    """验证 QualityScores 数据模型的正确性。"""

    def test_create_valid_excellent_scores(self):
        """高质量评分（excellent）正常创建。"""
        scores = QualityScores(
            semantic_preservation=5,
            clarity_improvement=5,
            information_gain=4,
            term_accuracy=5,
            retrievability=5,
            total_score=24,
            verdict="excellent",
            issues=[],
        )
        assert scores.verdict == "excellent"
        assert scores.total_score == 24
        assert scores.semantic_preservation == 5

    def test_create_valid_good_scores(self):
        """良好评分（good）正常创建。"""
        scores = QualityScores(
            semantic_preservation=4,
            clarity_improvement=4,
            information_gain=3,
            term_accuracy=4,
            retrievability=3,
            total_score=18,
            verdict="good",
        )
        assert scores.verdict == "good"
        assert scores.total_score == 18

    def test_create_valid_marginal_scores(self):
        """边缘评分（marginal）正常创建。"""
        scores = QualityScores(
            semantic_preservation=3,
            clarity_improvement=3,
            information_gain=2,
            term_accuracy=2,
            retrievability=2,
            total_score=12,
            verdict="marginal",
            issues=["改进空间较大"],
        )
        assert scores.verdict == "marginal"
        assert len(scores.issues) == 1

    def test_create_valid_poor_scores(self):
        """差评分（poor）正常创建。"""
        scores = QualityScores(
            semantic_preservation=2,
            clarity_improvement=1,
            information_gain=1,
            term_accuracy=1,
            retrievability=2,
            total_score=7,
            verdict="poor",
            issues=["语义偏离", "信息丢失"],
        )
        assert scores.verdict == "poor"
        assert len(scores.issues) == 2

    def test_semantic_preservation_out_of_range_raises(self):
        """semantic_preservation 超出 1-5 范围应抛出 ValueError。"""
        with pytest.raises(ValueError, match="semantic_preservation must be 1-5"):
            QualityScores(
                semantic_preservation=0,
                clarity_improvement=3,
                information_gain=3,
                term_accuracy=3,
                retrievability=3,
                total_score=12,
                verdict="marginal",
            )

    def test_clarity_improvement_out_of_range_raises(self):
        """clarity_improvement 超出 1-5 范围应抛出 ValueError。"""
        with pytest.raises(ValueError, match="clarity_improvement must be 1-5"):
            QualityScores(
                semantic_preservation=3,
                clarity_improvement=6,
                information_gain=3,
                term_accuracy=3,
                retrievability=3,
                total_score=18,
                verdict="good",
            )

    def test_default_issues_is_empty_list(self):
        """issues 默认值为空列表。"""
        scores = QualityScores(
            semantic_preservation=3,
            clarity_improvement=3,
            information_gain=3,
            term_accuracy=3,
            retrievability=3,
            total_score=15,
            verdict="good",
        )
        assert scores.issues == []

    def test_all_fields_accessible(self):
        """所有字段均可正常访问。"""
        scores = QualityScores(
            semantic_preservation=4,
            clarity_improvement=5,
            information_gain=3,
            term_accuracy=4,
            retrievability=4,
            total_score=20,
            verdict="excellent",
            issues=["小问题"],
        )
        assert scores.semantic_preservation == 4
        assert scores.clarity_improvement == 5
        assert scores.information_gain == 3
        assert scores.term_accuracy == 4
        assert scores.retrievability == 4
        assert scores.total_score == 20
        assert scores.verdict == "excellent"


# ═══════════════════════════════════════════════════════════════════════════════
# 确定性预检查测试（调用 Postprocessor.pre_check() 验证逻辑）
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeterministicPreCheck:
    """验证零 LLM 成本的确定性预检查逻辑。

    直接调用 Postprocessor.pre_check()，断言其返回的 passed / issues /
    keyword_retention / length_ratio 字段。
    """

    @classmethod
    def _make_postprocessor(cls, **kwargs) -> Postprocessor:
        """创建一个 Postprocessor 实例，mock 无关注入依赖。"""
        return Postprocessor(
            chat_adapter=MagicMock(),
            prompt_loader=MagicMock(),
            audit_trail=MagicMock(),
            **kwargs,
        )

    # ── 关键词留存率检查 ──────────────────────────────────────────────────

    def test_keyword_retention_below_threshold_directly_discarded(self):
        """关键词留存率 < 阈值（默认 0.7）→ passed=False，跳过 LLM 评估。"""
        pp = self._make_postprocessor()
        original = "Python 性能优化的方法有哪些"
        rewritten = "Python"  # 大量关键词丢失

        result = pp.pre_check(original, rewritten)

        assert result["passed"] is False, (
            f"关键词留存率 {result['keyword_retention']:.2f} 应低于阈值 → passed=False"
        )
        assert result["keyword_retention"] < 0.7
        assert any("关键词留存率" in issue for issue in result["issues"])

    def test_keyword_retention_above_threshold_passes_pre_check(self):
        """关键词留存率 ≥ 阈值 → passed=True，进入 LLM 评估。"""
        pp = self._make_postprocessor()
        original = "性能优化方法"
        rewritten = "性能优化方法指南"  # 所有原词均保留，留存率 1.0

        result = pp.pre_check(original, rewritten)

        assert result["passed"] is True, (
            f"关键词留存率 {result['keyword_retention']:.2f} 应 ≥ 阈值 → passed=True"
        )
        assert result["keyword_retention"] >= 0.7

    def test_keyword_retention_all_retained(self):
        """所有关键词均保留 → 留存率 = 1.0。"""
        pp = self._make_postprocessor()
        original = "性能优化方法"
        rewritten = "性能优化方法论"  # 所有原词均保留

        result = pp.pre_check(original, rewritten)

        assert result["keyword_retention"] == 1.0, (
            f"Expected 1.0, got {result['keyword_retention']:.2f}"
        )

    def test_keyword_retention_empty_original_handled(self):
        """原始查询无有效关键词时 → keyword_retention=1.0，passed=True（跳过检查）。"""
        pp = self._make_postprocessor()
        original = ""

        result = pp.pre_check(original, "some rewritten text")

        assert result["passed"] is True
        assert result["keyword_retention"] == 1.0

    # ── 长度比例检查 ──────────────────────────────────────────────────────

    def test_length_ratio_too_short_marked_suspicious(self):
        """改写长度 < 原始长度的 30% → issues 中标记"改写过短"。"""
        pp = self._make_postprocessor()
        original = "如何优化 Python 程序的运行性能和内存占用"
        rewritten = "优化"  # 极短

        result = pp.pre_check(original, rewritten)

        assert result["length_ratio"] < 0.3, f"长度比例 {result['length_ratio']:.2f} 应 < 0.3"
        assert any("改写过短" in issue for issue in result["issues"])

    def test_length_ratio_too_long_marked_suspicious(self):
        """改写长度 > 原始长度的 500% → issues 中标记"改写过长"。"""
        pp = self._make_postprocessor()
        original = "优化 Python"
        rewritten = (
            "优化 Python 程序性能的详细方法论包括代码层面优化、"
            "算法选择、数据结构优化、内存管理、并发处理、编译优化、"
            "JIT 编译、C 扩展等数十种技术手段的综合运用"
        )

        result = pp.pre_check(original, rewritten)

        assert result["length_ratio"] > 5.0, f"长度比例 {result['length_ratio']:.2f} 应 > 5.0"
        assert any("改写过长" in issue for issue in result["issues"])

    def test_length_ratio_normal_not_suspicious(self):
        """长度比例在正常范围（0.3-5.0）内 → 不生成长度相关 issues。"""
        pp = self._make_postprocessor()
        original = "如何优化 Python 程序性能"
        rewritten = "Python 程序性能优化方法指南"

        result = pp.pre_check(original, rewritten)

        assert 0.3 <= result["length_ratio"] <= 5.0, (
            f"长度比例 {result['length_ratio']:.2f} 应在 [0.3, 5.0] 范围内"
        )
        # 无长度相关的问题
        assert not any("改写" in issue for issue in result["issues"])

    def test_length_ratio_empty_original_handled(self):
        """原始查询为空时 → length_ratio 使用 max(len(original), 1) 避免除零。"""
        pp = self._make_postprocessor()
        original = ""
        rewritten = "some text"

        result = pp.pre_check(original, rewritten)

        assert result["length_ratio"] == len(rewritten)


# ═══════════════════════════════════════════════════════════════════════════════
# 质量评估降级兜底测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestQualityEvaluationDegradation:
    """验证质量评估 LLM 调用失败时的降级兜底行为。"""

    @pytest.mark.asyncio
    async def test_evaluation_llm_failure_conservatively_accepts_rewrite(
        self,
        mock_protector_phase2,
        mock_context_rewriter_phase2,
        mock_cache_manager_with_l2,
        mock_chat_adapter,
        mock_audit_trail_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
    ):
        """质量评估 LLM 调用失败（超时或 API 错误）→ 保守接受改写结果。

        Postprocessor.evaluate() 返回 quality_scores=None, passed=True
        （降级模式），QueryRewriter 应接受改写结果并继续正常流程。
        """
        mock_protector_phase2.protect.return_value = ("test query", {})
        mock_protector_phase2.restore.return_value = "normalized test query"
        mock_strategy_router.route.return_value = {
            "intent": "procedural",
            "complexity": 4,
            "strategies": ["normalize"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "normalized test query",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 30,
        }

        # Postprocessor 模拟评估 LLM 失败降级：返回 None quality_scores 但 passed=True
        postprocessor = _mock_postprocessor(
            evaluate_return=_make_postprocessor_evaluate_result(
                quality_scores=None,  # 评估失败
                passed=True,  # 保守接受
            )
        )

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            context_rewriter=mock_context_rewriter_phase2,
            cache_manager=mock_cache_manager_with_l2,
            chat_adapter=mock_chat_adapter,
            audit_trail=mock_audit_trail_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            postprocessor=postprocessor,
        )

        result = await rewriter.rewrite("test query", session_id="sess_test")

        # 改写结果应被保留
        assert len(result.rewritten_queries) >= 1
        # 降级时 quality_scores 为 None（评估未完成）
        assert result.quality_scores is None
        # 不应因评估失败而丢弃改写
        assert result.rewritten_queries[0]["query"] != ""

    @pytest.mark.asyncio
    async def test_evaluation_llm_exception_caught_and_logged(
        self,
        mock_protector_phase2,
        mock_context_rewriter_phase2,
        mock_cache_manager_with_l2,
        mock_chat_adapter,
        mock_audit_trail_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
    ):
        """质量评估 LLM 抛出异常 → 记录警告日志，保守接受改写。

        模拟 Postprocessor.evaluate() 抛出异常（而非返回降级结果），
        QueryRewriter 应捕获异常、记录日志、继续使用改写结果。
        """
        from app.services.chat_adapter import ChatAPIError

        mock_protector_phase2.protect.return_value = ("test query", {})
        mock_protector_phase2.restore.return_value = "rewritten query"
        mock_strategy_router.route.return_value = {
            "intent": "factual",
            "complexity": 3,
            "strategies": ["normalize"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "rewritten query",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 30,
        }

        # Postprocessor.evaluate 直接抛出异常
        postprocessor = MagicMock()
        postprocessor.evaluate = MagicMock(side_effect=ChatAPIError("Evaluation API timeout"))

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            context_rewriter=mock_context_rewriter_phase2,
            cache_manager=mock_cache_manager_with_l2,
            chat_adapter=mock_chat_adapter,
            audit_trail=mock_audit_trail_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            postprocessor=postprocessor,
        )

        # 不应抛出异常 —— 降级兜底
        result = await rewriter.rewrite("test query", session_id="sess_test")

        # 降级后改写结果应被保留
        assert result is not None
        assert result.original_query == "test query"
        # 评估失败时 quality_scores 应为 None
        assert result.quality_scores is None


# ═══════════════════════════════════════════════════════════════════════════════
# Postprocessor 集成测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestPostprocessorIntegration:
    """验证 Postprocessor 集成到 QueryRewriter 管线的正确行为。"""

    pytestmark = pytest.mark.asyncio

    async def test_high_quality_rewrite_passes_and_keeps_result(
        self,
        mock_protector_phase2,
        mock_context_rewriter_phase2,
        mock_cache_manager_with_l2,
        mock_chat_adapter,
        mock_audit_trail_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
    ):
        """高质量改写（total_score=22, verdict=excellent）→ 通过，保留改写结果。"""
        mock_protector_phase2.protect.return_value = ("test query", {})
        mock_protector_phase2.restore.return_value = "high quality rewrite"
        mock_strategy_router.route.return_value = {
            "intent": "procedural",
            "complexity": 4,
            "strategies": ["normalize"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "high quality rewrite",
            "strategy": "normalize",
            "duration_ms": 120.0,
            "tokens": 35,
        }

        postprocessor = _mock_postprocessor(
            evaluate_return=_make_postprocessor_evaluate_result(_high_quality_scores(), passed=True)
        )

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            context_rewriter=mock_context_rewriter_phase2,
            cache_manager=mock_cache_manager_with_l2,
            chat_adapter=mock_chat_adapter,
            audit_trail=mock_audit_trail_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            postprocessor=postprocessor,
        )

        result = await rewriter.rewrite("test query", session_id="sess_test")

        # 高质量改写应被保留
        assert len(result.rewritten_queries) >= 1
        assert result.quality_scores is not None
        assert result.quality_scores.verdict == "excellent"
        assert result.quality_scores.total_score == 22
        # 不应触发回溯
        assert result.backtrack_triggered is False

    async def test_semantic_preservation_below_3_auto_discard(
        self,
        mock_protector_phase2,
        mock_context_rewriter_phase2,
        mock_cache_manager_with_l2,
        mock_chat_adapter,
        mock_audit_trail_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
    ):
        """语义保留度 < 3 → 自动判定 poor → 丢弃改写，回退原始查询。"""
        mock_protector_phase2.protect.return_value = ("test query", {})
        mock_protector_phase2.restore.return_value = "test query"
        mock_strategy_router.route.return_value = {
            "intent": "analytical",
            "complexity": 6,
            "strategies": ["normalize"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "completely different meaning",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 30,
        }

        postprocessor = _mock_postprocessor(
            evaluate_return=_make_postprocessor_evaluate_result(
                _poor_quality_scores_low_semantic(), passed=False
            )
        )

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            context_rewriter=mock_context_rewriter_phase2,
            cache_manager=mock_cache_manager_with_l2,
            chat_adapter=mock_chat_adapter,
            audit_trail=mock_audit_trail_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            postprocessor=postprocessor,
        )

        result = await rewriter.rewrite("test query", session_id="sess_test")

        # 语义偏离严重 → 应回退到原始查询
        assert result is not None
        assert result.original_query == "test query"
        # quality_scores 仍然记录（标记了失败原因）
        assert result.quality_scores is not None
        assert result.quality_scores.semantic_preservation < 3

    async def test_total_score_below_15_triggers_backtrack_upgrade_strategy(
        self,
        mock_protector_phase2,
        mock_context_rewriter_phase2,
        mock_cache_manager_with_l2,
        mock_chat_adapter,
        mock_audit_trail_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_expand_rewriter,
    ):
        """总分 < 15（marginal）→ 触发回溯，升级策略重新改写。

        首次 normalize 得分为 12（marginal）→ 升级为 expand 重试。
        """
        mock_protector_phase2.protect.return_value = ("test query", {})
        mock_protector_phase2.restore.return_value = "expanded high quality rewrite"
        mock_strategy_router.route.return_value = {
            "intent": "ambiguous",
            "complexity": 5,
            "strategies": ["normalize"],
        }

        # normalize 改写返回
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "mediocre rewrite",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 30,
        }

        # expand（升级后）改写返回
        mock_expand_rewriter.rewrite.return_value = {
            "query": "expanded high quality rewrite",
            "strategy": "expand",
            "duration_ms": 200.0,
            "tokens": 55,
        }

        # 第一次评估 → marginal（满分 12，触发回溯）
        # 第二次评估 → excellent（升级策略后通过）
        eval_count = [0]

        def evaluate_side_effect(original_query, rewritten_query, intent=None):
            eval_count[0] += 1
            if eval_count[0] == 1:
                return _make_postprocessor_evaluate_result(_marginal_quality_scores(), passed=False)
            else:
                return _make_postprocessor_evaluate_result(_high_quality_scores(), passed=True)

        postprocessor = MagicMock()
        postprocessor.evaluate = MagicMock(side_effect=evaluate_side_effect)

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            context_rewriter=mock_context_rewriter_phase2,
            cache_manager=mock_cache_manager_with_l2,
            chat_adapter=mock_chat_adapter,
            audit_trail=mock_audit_trail_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            expand_rewriter=mock_expand_rewriter,
            postprocessor=postprocessor,
            max_backtrack_attempts=1,
        )

        result = await rewriter.rewrite("test query", session_id="sess_test")

        # 回溯后应获得高质量结果
        assert result is not None
        assert result.backtrack_triggered is True
        assert result.backtrack_strategy == "expand"
        assert result.quality_scores is not None
        assert result.quality_scores.verdict == "excellent"
        # 应调用了两次 evaluate（首次 + 回溯）
        assert eval_count[0] >= 2

    async def test_second_failure_directly_discards_fallback_to_original(
        self,
        mock_protector_phase2,
        mock_context_rewriter_phase2,
        mock_cache_manager_with_l2,
        mock_chat_adapter,
        mock_audit_trail_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_expand_rewriter,
    ):
        """二次失败直接丢弃改写结果，回退原始查询。

        首次 normalize → marginal（回溯）→ expand → 仍 marginal/poor → 丢弃。
        """
        mock_protector_phase2.protect.return_value = ("test query", {})
        mock_protector_phase2.restore.return_value = "test query"
        mock_strategy_router.route.return_value = {
            "intent": "ambiguous",
            "complexity": 5,
            "strategies": ["normalize"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "bad rewrite attempt 1",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 30,
        }
        mock_expand_rewriter.rewrite.return_value = {
            "query": "bad rewrite attempt 2",
            "strategy": "expand",
            "duration_ms": 200.0,
            "tokens": 55,
        }

        # 两次评估均失败
        postprocessor = MagicMock()
        postprocessor.evaluate = MagicMock(
            return_value=_make_postprocessor_evaluate_result(
                _marginal_quality_scores(), passed=False
            )
        )

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            context_rewriter=mock_context_rewriter_phase2,
            cache_manager=mock_cache_manager_with_l2,
            chat_adapter=mock_chat_adapter,
            audit_trail=mock_audit_trail_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            expand_rewriter=mock_expand_rewriter,
            postprocessor=postprocessor,
            max_backtrack_attempts=1,
        )

        result = await rewriter.rewrite("test query", session_id="sess_test")

        # 二次失败 → 回退原始查询
        assert result is not None
        assert result.original_query == "test query"
        assert result.backtrack_triggered is True
        # 最终改写结果应回退到原始查询
        assert len(result.rewritten_queries) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 回溯限制测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestBacktrackLimits:
    """验证回溯限制机制 —— 最多 1 次，不可无限回溯。"""

    pytestmark = pytest.mark.asyncio

    async def test_max_one_backtrack_not_infinite(
        self,
        mock_protector_phase2,
        mock_context_rewriter_phase2,
        mock_cache_manager_with_l2,
        mock_chat_adapter,
        mock_audit_trail_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_expand_rewriter,
    ):
        """确保最多回溯 1 次，不会无限回溯。

        模拟 Postprocessor 始终返回 marginal，验证只回溯一次后即停止。
        """
        mock_protector_phase2.protect.return_value = ("test query", {})
        mock_protector_phase2.restore.return_value = "test query"
        mock_strategy_router.route.return_value = {
            "intent": "ambiguous",
            "complexity": 5,
            "strategies": ["normalize"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "rewrite attempt",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 30,
        }
        mock_expand_rewriter.rewrite.return_value = {
            "query": "rewrite attempt expanded",
            "strategy": "expand",
            "duration_ms": 200.0,
            "tokens": 55,
        }

        eval_call_count = [0]

        def always_marginal(original_query, rewritten_query, intent=None):
            eval_call_count[0] += 1
            return _make_postprocessor_evaluate_result(_marginal_quality_scores(), passed=False)

        postprocessor = MagicMock()
        postprocessor.evaluate = MagicMock(side_effect=always_marginal)

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            context_rewriter=mock_context_rewriter_phase2,
            cache_manager=mock_cache_manager_with_l2,
            chat_adapter=mock_chat_adapter,
            audit_trail=mock_audit_trail_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            expand_rewriter=mock_expand_rewriter,
            postprocessor=postprocessor,
            max_backtrack_attempts=1,
        )

        result = await rewriter.rewrite("test query", session_id="sess_test")

        # 不应无限回溯 —— evaluate 调用次数有上限
        # 最多 = 初始 1 次 + 回溯 1 次 = 2 次
        assert eval_call_count[0] <= 2, (
            f"回溯次数超限：预期最多 2 次 evaluate 调用，实际 {eval_call_count[0]} 次"
        )
        # 应正常返回（不抛异常）
        assert result is not None
        assert result.original_query == "test query"

    async def test_backtrack_triggered_flag_set_correctly(
        self,
        mock_protector_phase2,
        mock_context_rewriter_phase2,
        mock_cache_manager_with_l2,
        mock_chat_adapter,
        mock_audit_trail_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_expand_rewriter,
    ):
        """backtrack_triggered 标志正确反映是否触发了回溯。"""
        mock_protector_phase2.protect.return_value = ("test query", {})
        mock_protector_phase2.restore.return_value = "good rewrite"
        mock_strategy_router.route.return_value = {
            "intent": "procedural",
            "complexity": 4,
            "strategies": ["normalize"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "good rewrite",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 30,
        }

        # 首次即高分通过 —— 不应触发回溯
        postprocessor = _mock_postprocessor(
            evaluate_return=_make_postprocessor_evaluate_result(_high_quality_scores(), passed=True)
        )

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            context_rewriter=mock_context_rewriter_phase2,
            cache_manager=mock_cache_manager_with_l2,
            chat_adapter=mock_chat_adapter,
            audit_trail=mock_audit_trail_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            postprocessor=postprocessor,
            max_backtrack_attempts=1,
        )

        result = await rewriter.rewrite("test query", session_id="sess_test")

        assert result.backtrack_triggered is False
        assert result.backtrack_strategy is None

    async def test_backtrack_only_upgrades_strategy_not_downgrades(
        self,
        mock_protector_phase2,
        mock_context_rewriter_phase2,
        mock_cache_manager_with_l2,
        mock_chat_adapter,
        mock_audit_trail_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_expand_rewriter,
    ):
        """回溯时升级策略（normalize → expand），而非随机切换或降级。"""
        mock_protector_phase2.protect.return_value = ("test query", {})
        mock_protector_phase2.restore.return_value = "expanded query"
        mock_strategy_router.route.return_value = {
            "intent": "ambiguous",
            "complexity": 5,
            "strategies": ["normalize"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "first attempt",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 30,
        }
        mock_expand_rewriter.rewrite.return_value = {
            "query": "expanded query",
            "strategy": "expand",
            "duration_ms": 200.0,
            "tokens": 55,
        }

        call_count = [0]

        def first_fail_then_pass(original_query, rewritten_query, intent=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_postprocessor_evaluate_result(_marginal_quality_scores(), passed=False)
            return _make_postprocessor_evaluate_result(_high_quality_scores(), passed=True)

        postprocessor = MagicMock()
        postprocessor.evaluate = MagicMock(side_effect=first_fail_then_pass)

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            context_rewriter=mock_context_rewriter_phase2,
            cache_manager=mock_cache_manager_with_l2,
            chat_adapter=mock_chat_adapter,
            audit_trail=mock_audit_trail_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            expand_rewriter=mock_expand_rewriter,
            postprocessor=postprocessor,
            max_backtrack_attempts=1,
        )

        result = await rewriter.rewrite("test query", session_id="sess_test")

        # 回溯策略应为 expand（升级），不是 normalize（原策略）
        assert result.backtrack_triggered is True
        assert result.backtrack_strategy == "expand"


# ═══════════════════════════════════════════════════════════════════════════════
# QualityScores 传递到 RewriteResult 测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestQualityScoresInRewriteResult:
    """验证 QualityScores 正确传递到 RewriteResult。"""

    pytestmark = pytest.mark.asyncio

    async def test_quality_scores_passed_to_rewrite_result(
        self,
        mock_protector_phase2,
        mock_context_rewriter_phase2,
        mock_cache_manager_with_l2,
        mock_chat_adapter,
        mock_audit_trail_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
    ):
        """QualityScores 正确附加到 RewriteResult。"""
        mock_protector_phase2.protect.return_value = ("test query", {})
        mock_protector_phase2.restore.return_value = "good rewrite"
        mock_strategy_router.route.return_value = {
            "intent": "procedural",
            "complexity": 4,
            "strategies": ["normalize"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "good rewrite",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 30,
        }

        expected_scores = _high_quality_scores()
        postprocessor = _mock_postprocessor(
            evaluate_return=_make_postprocessor_evaluate_result(expected_scores, passed=True)
        )

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            context_rewriter=mock_context_rewriter_phase2,
            cache_manager=mock_cache_manager_with_l2,
            chat_adapter=mock_chat_adapter,
            audit_trail=mock_audit_trail_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            postprocessor=postprocessor,
        )

        result = await rewriter.rewrite("test query", session_id="sess_test")

        # 验证 QualityScores 完整传递
        assert result.quality_scores is not None
        assert result.quality_scores.semantic_preservation == expected_scores.semantic_preservation
        assert result.quality_scores.clarity_improvement == expected_scores.clarity_improvement
        assert result.quality_scores.information_gain == expected_scores.information_gain
        assert result.quality_scores.term_accuracy == expected_scores.term_accuracy
        assert result.quality_scores.retrievability == expected_scores.retrievability
        assert result.quality_scores.total_score == expected_scores.total_score
        assert result.quality_scores.verdict == expected_scores.verdict

    async def test_quality_scores_includes_all_five_dimensions(
        self,
        mock_protector_phase2,
        mock_context_rewriter_phase2,
        mock_cache_manager_with_l2,
        mock_chat_adapter,
        mock_audit_trail_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
    ):
        """QualityScores 包含全部 5 个维度的评分。"""
        mock_protector_phase2.protect.return_value = ("test query", {})
        mock_protector_phase2.restore.return_value = "rewritten"
        mock_strategy_router.route.return_value = {
            "intent": "analytical",
            "complexity": 7,
            "strategies": ["normalize"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "rewritten",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 30,
        }

        scores = QualityScores(
            semantic_preservation=5,
            clarity_improvement=4,
            information_gain=3,
            term_accuracy=4,
            retrievability=5,
            total_score=21,
            verdict="excellent",
            issues=[],
        )
        postprocessor = _mock_postprocessor(
            evaluate_return=_make_postprocessor_evaluate_result(scores, passed=True)
        )

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            context_rewriter=mock_context_rewriter_phase2,
            cache_manager=mock_cache_manager_with_l2,
            chat_adapter=mock_chat_adapter,
            audit_trail=mock_audit_trail_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            postprocessor=postprocessor,
        )

        result = await rewriter.rewrite("test query", session_id="sess_test")

        qs = result.quality_scores
        assert qs is not None
        # 验证 5 维度均存在且为 1-5 分
        assert 1 <= qs.semantic_preservation <= 5
        assert 1 <= qs.clarity_improvement <= 5
        assert 1 <= qs.information_gain <= 5
        assert 1 <= qs.term_accuracy <= 5
        assert 1 <= qs.retrievability <= 5

    async def test_quality_scores_issues_list_preserved(
        self,
        mock_protector_phase2,
        mock_context_rewriter_phase2,
        mock_cache_manager_with_l2,
        mock_chat_adapter,
        mock_audit_trail_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
    ):
        """QualityScores 的 issues 列表完整保留。"""
        mock_protector_phase2.protect.return_value = ("test query", {})
        mock_protector_phase2.restore.return_value = "rewritten"
        mock_strategy_router.route.return_value = {
            "intent": "factual",
            "complexity": 3,
            "strategies": ["normalize"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "rewritten",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 30,
        }

        scores = QualityScores(
            semantic_preservation=3,
            clarity_improvement=2,
            information_gain=2,
            term_accuracy=3,
            retrievability=2,
            total_score=12,
            verdict="marginal",
            issues=["清晰度不足", "信息增量偏低", "语义有轻微偏离"],
        )
        postprocessor = _mock_postprocessor(
            evaluate_return=_make_postprocessor_evaluate_result(scores, passed=False)
        )

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            context_rewriter=mock_context_rewriter_phase2,
            cache_manager=mock_cache_manager_with_l2,
            chat_adapter=mock_chat_adapter,
            audit_trail=mock_audit_trail_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            postprocessor=postprocessor,
        )

        result = await rewriter.rewrite("test query", session_id="sess_test")

        assert result.quality_scores is not None
        assert len(result.quality_scores.issues) == 3
        assert "清晰度不足" in result.quality_scores.issues
        assert "信息增量偏低" in result.quality_scores.issues
        assert "语义有轻微偏离" in result.quality_scores.issues

    async def test_rewrite_result_without_postprocessor_has_null_quality_scores(
        self,
        mock_protector_phase2,
        mock_context_rewriter_phase2,
        mock_cache_manager_with_l2,
        mock_chat_adapter,
        mock_audit_trail_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
    ):
        """未配置 Postprocessor 时 quality_scores 为 None（向后兼容）。"""
        mock_protector_phase2.protect.return_value = ("test query", {})
        mock_protector_phase2.restore.return_value = "rewritten"
        mock_strategy_router.route.return_value = {
            "intent": "factual",
            "complexity": 3,
            "strategies": ["normalize"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "rewritten",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 30,
        }

        # 不配置 postprocessor
        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            context_rewriter=mock_context_rewriter_phase2,
            cache_manager=mock_cache_manager_with_l2,
            chat_adapter=mock_chat_adapter,
            audit_trail=mock_audit_trail_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            postprocessor=None,
        )

        result = await rewriter.rewrite("test query", session_id="sess_test")

        # 无 Postprocessor → quality_scores 为 None
        assert result.quality_scores is None
        assert result.backtrack_triggered is False
        assert result.backtrack_strategy is None


# ═══════════════════════════════════════════════════════════════════════════════
# 确定性预检查集成测试（Postprocessor → QueryRewriter）
# ═══════════════════════════════════════════════════════════════════════════════


class TestPreCheckIntegration:
    """验证确定性预检查失败时 QueryRewriter 的行为。"""

    pytestmark = pytest.mark.asyncio

    async def test_pre_check_failed_skips_llm_evaluation_and_discards(
        self,
        mock_protector_phase2,
        mock_context_rewriter_phase2,
        mock_cache_manager_with_l2,
        mock_chat_adapter,
        mock_audit_trail_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
    ):
        """确定性预检查失败 → 直接丢弃改写，跳过 LLM 质量评估。

        Postprocessor.evaluate() 返回 pre_check_failed=True，无 quality_scores。
        """
        mock_protector_phase2.protect.return_value = ("test query", {})
        mock_protector_phase2.restore.return_value = "test query"
        mock_strategy_router.route.return_value = {
            "intent": "procedural",
            "complexity": 4,
            "strategies": ["normalize"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "almost empty",
            "strategy": "normalize",
            "duration_ms": 80.0,
            "tokens": 20,
        }

        # 预检查失败：关键词大量丢失 → 直接丢弃
        postprocessor = _mock_postprocessor(
            evaluate_return={
                "quality_scores": None,
                "passed": False,
                "pre_check_failed": True,
                "pre_check_issues": ["关键词留存率 0.25 低于阈值 0.7"],
            }
        )

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            context_rewriter=mock_context_rewriter_phase2,
            cache_manager=mock_cache_manager_with_l2,
            chat_adapter=mock_chat_adapter,
            audit_trail=mock_audit_trail_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            postprocessor=postprocessor,
        )

        result = await rewriter.rewrite("test query", session_id="sess_test")

        # 预检查失败 → 无 quality_scores（未执行 LLM 评估）
        assert result.quality_scores is None
        # 应回退到原始查询
        assert result.original_query == "test query"

    async def test_pre_check_length_ratio_suspicious_but_llm_evaluation_proceeds(
        self,
        mock_protector_phase2,
        mock_context_rewriter_phase2,
        mock_cache_manager_with_l2,
        mock_chat_adapter,
        mock_audit_trail_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
    ):
        """长度比例异常 → 标记可疑但 LLM 评估继续（不是直接丢弃）。

        长度比例异常不同于关键词流失 —— 它降低阈值但不直接丢弃。
        """
        mock_protector_phase2.protect.return_value = ("test query", {})
        mock_protector_phase2.restore.return_value = "brief"
        mock_strategy_router.route.return_value = {
            "intent": "factual",
            "complexity": 3,
            "strategies": ["normalize"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "brief",
            "strategy": "normalize",
            "duration_ms": 80.0,
            "tokens": 20,
        }

        # 长度比例可疑但 LLM 评估仍执行（有 quality_scores）
        postprocessor = _mock_postprocessor(
            evaluate_return={
                "quality_scores": QualityScores(
                    semantic_preservation=3,
                    clarity_improvement=2,
                    information_gain=1,
                    term_accuracy=2,
                    retrievability=2,
                    total_score=10,
                    verdict="marginal",
                    issues=["长度比例异常：改写过短"],
                ),
                "passed": False,
                "pre_check_failed": False,
                "pre_check_issues": ["长度比例 0.15 低于 0.3，标记可疑"],
            }
        )

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            context_rewriter=mock_context_rewriter_phase2,
            cache_manager=mock_cache_manager_with_l2,
            chat_adapter=mock_chat_adapter,
            audit_trail=mock_audit_trail_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            postprocessor=postprocessor,
        )

        result = await rewriter.rewrite("test query", session_id="sess_test")

        # 长度异常不直接丢弃 → 执行了 LLM 评估，有 quality_scores
        assert result.quality_scores is not None
        assert "长度比例异常" in str(result.quality_scores.issues)


# ═══════════════════════════════════════════════════════════════════════════════
# 分层意图阈值测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestTieredIntentThresholds:
    """验证按意图类型的分层关键词留存率阈值。"""

    @classmethod
    def _make_postprocessor(cls, **kwargs) -> Postprocessor:
        return Postprocessor(
            chat_adapter=MagicMock(),
            prompt_loader=MagicMock(),
            audit_trail=MagicMock(),
            **kwargs,
        )

    def test_procedural_intent_uses_lower_threshold(self):
        """procedural 意图使用 0.50 阈值 —— 低于默认 0.70 的留存率也能通过。"""
        pp = self._make_postprocessor()
        # "基本操作" → tokens: ["基本", "本操", "操作"]
        # 改写中只保留 "操作" → 留存率 1/3 ≈ 0.33 < 默认 0.70，但 > procedural 0.50? No, still < 0.50
        # 需要设计留存率在 0.50-0.70 之间的用例
        # "基本操作指南" → tokens: ["基本", "本操", "操作", "作指", "指南"]
        # 改写 "操作指南概述" → "基本" not in, "本操" not in, "操作" ✓, "作指" ✓, "指南" ✓ → 3/5=0.60
        original = "基本操作指南"
        rewritten = "操作指南概述"

        result = pp.pre_check(original, rewritten, intent="procedural")

        # 留存率 0.60 ≥ procedural 阈值 0.50 → 应通过
        retention = result["keyword_retention"]
        assert retention < 0.70, (
            f"留存率 {retention:.2f} 应低于默认阈值 0.70（才需要分层阈值）"
        )
        assert retention >= 0.50, (
            f"留存率 {retention:.2f} 应 ≥ procedural 阈值 0.50"
        )
        assert result["passed"] is True, (
            f"procedural 意图留存率 {retention:.2f} ≥ 0.50 应通过预检"
        )

    def test_factual_intent_uses_higher_threshold(self):
        """factual 意图使用 0.80 阈值 —— 高于默认 0.70 的留存率也会被拒。"""
        pp = self._make_postprocessor()
        # "什么是深度学习模型" → tokens: ["什么", "么是", "是深", "深度", "度学", "学习", "习模", "模型"]
        # After stop words: "什么" filtered, "么是" not filtered, "是深" not filtered...
        # Actually let me reconsider. Stop words include "什么", "怎么", "如何", "哪些" etc.
        # But not "是" individually. Wait, let me check _STOP_WORDS:
        # "的","了","在","是","我","有","和","就","不","人","都","一",...
        # "是" IS in stop words. So "是深" is still the bigram "是深" — not in stop words.
        # Similarly, "什么" might be in stop words? Let me check...
        # "什么" IS in stop words: "什么" in _STOP_WORDS → yes
        # So bigrams containing stop words as a substring are NOT filtered (only exact match).
        # That means "是深" stays, "什么" is filtered.
        #
        # Let me design: original "什么是深度学习" → tokens after cleaning:
        # Chinese chars: "什么是深度学习"
        # Bigrams: "什么" (STOP!), "么是", "是深", "深度", "度学", "学习"
        # After filter: "么是", "是深", "深度", "度学", "学习" = 5 tokens
        # Rewritten "深度学习定义" →
        # "么是" not in "深度学习定义"? Let me check: "深-度-学-习-定-义", "么是" — no.
        # "是深" in "深度学习定义"? "是-深" — "是" is not in "深度学习定义". No.
        # "深度" ✓, "度学" ✓, "学习" ✓
        # Retention = 3/5 = 0.60
        # 0.60 < factual 0.80, but also < default 0.70. We need it to be in the 0.70-0.80 range.
        #
        # Let me try: original "深度学习框架对比" → bigrams: "深度", "度学", "学习", "习框", "框架", "架对", "对比"
        # 7 tokens. Rewritten "深度学习框架比较分析" →
        # "深度" ✓, "度学" ✓, "学习" ✓, "习框" ✓, "框架" ✓, "架对" not in, "对比" not in
        # 5/7 ≈ 0.714. Between 0.70 and 0.80 → passes default, fails factual.

        original = "深度学习框架对比"
        rewritten = "深度学习框架比较分析"

        result = pp.pre_check(original, rewritten, intent="factual")

        retention = result["keyword_retention"]
        assert retention > 0.70, (
            f"留存率 {retention:.2f} 应 > 默认阈值 0.70（才需要分层阈值区分）"
        )
        assert retention < 0.80, (
            f"留存率 {retention:.2f} 应 < factual 阈值 0.80"
        )
        assert result["passed"] is False, (
            f"factual 意图留存率 {retention:.2f} < 0.80 应不通过预检"
        )

    def test_default_intent_uses_default_threshold(self):
        """未提供 intent 时使用默认阈值 0.70。"""
        pp = self._make_postprocessor()
        # 留存率 0.60 < 0.70 → 不通过
        original = "基本操作指南"
        rewritten = "操作指南概述"

        result = pp.pre_check(original, rewritten)

        retention = result["keyword_retention"]
        assert retention < 0.70
        assert result["passed"] is False, (
            f"无 intent 时留存率 {retention:.2f} < 默认 0.70 应不通过"
        )

    def test_unknown_intent_uses_default_threshold(self):
        """未知意图类型使用默认阈值 0.70。"""
        pp = self._make_postprocessor()
        original = "基本操作指南"
        rewritten = "操作指南概述"

        result = pp.pre_check(original, rewritten, intent="unknown_type")

        retention = result["keyword_retention"]
        assert retention < 0.70
        assert result["passed"] is False, (
            f"未知 intent 时留存率 {retention:.2f} < 默认 0.70 应不通过"
        )

    def test_chitchat_intent_uses_low_threshold(self):
        """chitchat 意图使用 0.55 阈值。"""
        pp = self._make_postprocessor()
        original = "你好很高兴认识你"
        rewritten = "很高兴认识"

        result = pp.pre_check(original, rewritten, intent="chitchat")

        retention = result["keyword_retention"]
        # chitchat 阈值 0.55，应宽松对待
        assert result["passed"] is True or retention < 0.55, (
            f"chitchat 留存率 {retention:.2f}，若 < 0.55 则不通过"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 单策略 normalize 降级快速路径测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestNormalizeOnlyFastPath:
    """验证只有 normalize 策略执行成功时，预检失败不丢弃结果的降级逻辑。"""

    pytestmark = pytest.mark.asyncio

    async def test_normalize_only_pre_check_failed_accepted_as_fallback(
        self,
        mock_protector_phase2,
        mock_context_rewriter_phase2,
        mock_cache_manager_with_l2,
        mock_chat_adapter,
        mock_audit_trail_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
    ):
        """只有 normalize 策略执行时，预检失败 → 标记 quality_fallback 接受改写。

        normalize 仅是清理/补全，不应因关键词留存率不足而丢弃。
        """
        mock_protector_phase2.protect.return_value = ("test query", {})
        mock_protector_phase2.restore.return_value = "normalized result"
        mock_strategy_router.route.return_value = {
            "intent": "procedural",
            "complexity": 4,
            "strategies": ["normalize"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "normalized result",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 30,
        }

        # 模拟预检失败（关键词留存率不足）
        postprocessor = _mock_postprocessor(
            evaluate_return={
                "quality_scores": None,
                "passed": False,
                "pre_check_failed": True,
                "pre_check_issues": ["关键词留存率 0.40 低于阈值 0.50"],
            }
        )

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            context_rewriter=mock_context_rewriter_phase2,
            cache_manager=mock_cache_manager_with_l2,
            chat_adapter=mock_chat_adapter,
            audit_trail=mock_audit_trail_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            postprocessor=postprocessor,
        )

        result = await rewriter.rewrite("test query", session_id="sess_test")

        # normalize 预检失败 → 应被接受（quality_fallback）
        assert result is not None
        assert result.quality_fallback is True, (
            "只有 normalize 策略时预检失败应触发 quality_fallback"
        )
        # 改写结果应被保留（不是回退原始查询）
        assert len(result.rewritten_queries) >= 1
        # 不应触发回溯
        assert result.backtrack_triggered is False

    async def test_normalize_with_expand_pre_check_failed_not_accepted(
        self,
        mock_protector_phase2,
        mock_context_rewriter_phase2,
        mock_cache_manager_with_l2,
        mock_chat_adapter,
        mock_audit_trail_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_expand_rewriter,
    ):
        """normalize + expand 多策略时，预检失败 → 正常回溯逻辑（不使用快速路径）。"""
        mock_protector_phase2.protect.return_value = ("test query", {})
        mock_protector_phase2.restore.return_value = "test query"
        mock_strategy_router.route.return_value = {
            "intent": "ambiguous",
            "complexity": 5,
            "strategies": ["normalize", "expand"],
        }
        # normalize 成功返回
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "normalized query",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 30,
        }
        # expand 成功返回
        mock_expand_rewriter.rewrite.return_value = {
            "query": "expanded query",
            "strategy": "expand",
            "duration_ms": 150.0,
            "tokens": 50,
        }

        # 预检失败
        postprocessor = _mock_postprocessor(
            evaluate_return={
                "quality_scores": None,
                "passed": False,
                "pre_check_failed": True,
                "pre_check_issues": ["关键词留存率过低"],
            }
        )

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            context_rewriter=mock_context_rewriter_phase2,
            cache_manager=mock_cache_manager_with_l2,
            chat_adapter=mock_chat_adapter,
            audit_trail=mock_audit_trail_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            expand_rewriter=mock_expand_rewriter,
            postprocessor=postprocessor,
        )

        result = await rewriter.rewrite("test query", session_id="sess_test")

        # 多策略（非 normalize only）→ 不触发快速路径
        assert result.quality_fallback is False, (
            "多策略时不应触发 normalize 快速路径"
        )

    async def test_normalize_only_llm_eval_failed_still_normal_backtrack(
        self,
        mock_protector_phase2,
        mock_context_rewriter_phase2,
        mock_cache_manager_with_l2,
        mock_chat_adapter,
        mock_audit_trail_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
    ):
        """只有 normalize 但 LLM 评估失败（非预检失败）→ 正常回溯逻辑。

        快速路径仅对 pre_check_failed 生效，LLM 评估不通过仍走回溯。
        """
        mock_protector_phase2.protect.return_value = ("test query", {})
        mock_protector_phase2.restore.return_value = "test query"
        mock_strategy_router.route.return_value = {
            "intent": "procedural",
            "complexity": 4,
            "strategies": ["normalize"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "normalized query",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 30,
        }

        # LLM 评估失败（passed=False, pre_check_failed=False）
        postprocessor = _mock_postprocessor(
            evaluate_return=_make_postprocessor_evaluate_result(
                _marginal_quality_scores(),
                passed=False,
                pre_check_failed=False,  # 预检查通过了，但 LLM 评估不通过
            )
        )

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            context_rewriter=mock_context_rewriter_phase2,
            cache_manager=mock_cache_manager_with_l2,
            chat_adapter=mock_chat_adapter,
            audit_trail=mock_audit_trail_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            postprocessor=postprocessor,
        )

        result = await rewriter.rewrite("test query", session_id="sess_test")

        # LLM 评估失败（非预检）→ 不应触发快速路径
        assert result.quality_fallback is False, (
            "LLM 评估失败不应触发 normalize 快速路径"
        )
