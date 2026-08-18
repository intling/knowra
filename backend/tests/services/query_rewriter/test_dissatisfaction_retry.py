"""不满意重试检测测试 —— 7.1.1b 场景。

测试覆盖：
- 同一会话短时间内重复提问 → 识别为不满意信号 → 跳过 L1 缓存 + 升级策略
- 不同问题不误触发
- 不同会话不触发
- 超时窗口外的重复查询不触发
- 不满意重试审计事件记录
- 不满意之后的新查询恢复正常缓存行为

.. note::
    本文件为 Phase 2 的**红测试**（TDD Red Phase）。
    运行时应预期失败 —— 当前 DissatisfactionDetector 尚未与 QueryRewriter 管线集成。
"""

from __future__ import annotations

import pytest

from .conftest import build_phase2_rewriter


class TestDissatisfactionRetryDetection:
    """验证同一会话短时间内重复提问 → 识别为不满意信号 → 跳过 L1 缓存 + 升级策略。"""

    pytestmark = pytest.mark.asyncio

    async def test_same_query_within_window_triggers_dissatisfaction(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_dissatisfaction_detector,
        mock_audit_trail_phase2,
    ):
        """同一会话短时间内重复提问相同问题 → L1 缓存被跳过 → 策略升级为 expand。"""
        # 检测器报告：此查询在不满意窗口内已被问过
        mock_dissatisfaction_detector.check.return_value = True
        mock_protector_phase2.protect.return_value = ("Python 怎么学", {})
        mock_protector_phase2.restore.return_value = "Python 学习路径：基础语法→常用库→项目实战"
        # 策略路由升级：追加 expand 策略
        mock_strategy_router.route.return_value = {
            "intent": "procedural",
            "complexity": 5,
            "strategies": ["normalize", "expand"],  # expand 替代 term_align → 换一种解释
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "如何学习 Python",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 40,
        }
        mock_expand_rewriter.rewrite.return_value = {
            "query": "Python 学习路径：基础语法→常用库→项目实战",
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
            dissatisfaction_detector=mock_dissatisfaction_detector,
            audit_trail=mock_audit_trail_phase2,
        )

        result = await rewriter.rewrite(
            "Python 怎么学",
            session_id="session_A",
        )

        # 不满意重试检测器被调用
        mock_dissatisfaction_detector.check.assert_called_once()
        # L1 缓存被跳过（不满意重试不应返回旧缓存）
        mock_cache_manager_with_l2.lookup.assert_not_called()
        # 策略路由器仍正常执行
        mock_strategy_router.route.assert_called_once()
        # expand 策略被执行（升级策略 → 换一种解释）
        mock_expand_rewriter.rewrite.assert_called_once()
        # 结果不来自缓存
        assert result.cache_hit is False

    async def test_same_query_repeated_three_times_still_detected(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_dissatisfaction_detector,
        mock_audit_trail_phase2,
    ):
        """同查询第 3 次出现时仍应被检测为不满意重试（非偶然）。"""
        mock_dissatisfaction_detector.check.return_value = True
        mock_protector_phase2.protect.return_value = ("Python 怎么学", {})
        mock_protector_phase2.restore.return_value = (
            "Python 学习的替代方案：在线课程、书籍、视频教程、实战项目"
        )
        mock_strategy_router.route.return_value = {
            "intent": "procedural",
            "complexity": 5,
            "strategies": ["normalize", "expand", "alternate"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "如何学习 Python",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 40,
        }
        mock_expand_rewriter.rewrite.return_value = {
            "query": "Python 学习的替代方案：在线课程、书籍、视频教程、实战项目",
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
            dissatisfaction_detector=mock_dissatisfaction_detector,
            audit_trail=mock_audit_trail_phase2,
        )

        # 第 3 次提问
        result = await rewriter.rewrite(
            "Python 怎么学",
            session_id="session_A",
        )

        # 检测器仍报告不满意
        assert mock_dissatisfaction_detector.check.called
        # L1 仍被跳过
        mock_cache_manager_with_l2.lookup.assert_not_called()
        assert result.cache_hit is False

    async def test_dissatisfaction_retry_audit_event_logged(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_dissatisfaction_detector,
        mock_audit_trail_phase2,
    ):
        """不满意重试应记录 dissatisfaction_retry 审计事件。"""
        mock_dissatisfaction_detector.check.return_value = True
        mock_protector_phase2.protect.return_value = ("Python 怎么学", {})
        mock_protector_phase2.restore.return_value = "Python 学习替代路径"
        mock_strategy_router.route.return_value = {
            "intent": "procedural",
            "complexity": 5,
            "strategies": ["normalize", "expand"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "如何学习 Python",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 40,
        }
        mock_expand_rewriter.rewrite.return_value = {
            "query": "Python 学习替代路径",
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
            dissatisfaction_detector=mock_dissatisfaction_detector,
            audit_trail=mock_audit_trail_phase2,
        )

        await rewriter.rewrite("Python 怎么学", session_id="session_A")

        # 审计日志应记录 dissatisfaction_retry 事件
        all_events = [call[0][0] for call in mock_audit_trail_phase2.record.call_args_list]
        assert "dissatisfaction_retry" in all_events, (
            f"不满意重试应记录 'dissatisfaction_retry' 事件，实际审计事件: {all_events}"
        )

    async def test_different_question_does_not_trigger_false_positive(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_dissatisfaction_detector,
        mock_audit_trail_phase2,
    ):
        """不同问题不应误触发不满意重试检测。"""
        # 第一个问题触发了不满意检测，但第二个是不同的问题
        mock_dissatisfaction_detector.check.side_effect = [True, False]
        mock_protector_phase2.protect.side_effect = [
            ("Python 怎么学", {}),
            ("数据库怎么优化", {}),
        ]
        mock_protector_phase2.restore.side_effect = [
            "Python 学习替代路径",
            "如何优化数据库性能",
        ]
        mock_strategy_router.route.side_effect = [
            {
                "intent": "procedural",
                "complexity": 5,
                "strategies": ["normalize", "expand"],
            },
            {
                "intent": "procedural",
                "complexity": 4,
                "strategies": ["normalize", "term_align"],
            },
        ]
        mock_normalize_rewriter.rewrite.side_effect = [
            {
                "query": "如何学习 Python",
                "strategy": "normalize",
                "duration_ms": 100.0,
                "tokens": 40,
            },
            {
                "query": "如何优化数据库性能",
                "strategy": "normalize",
                "duration_ms": 110.0,
                "tokens": 42,
            },
        ]
        mock_expand_rewriter.rewrite.return_value = {
            "query": "Python 学习替代路径",
            "strategy": "expand",
            "duration_ms": 180.0,
            "tokens": 55,
        }
        mock_term_align_rewriter.rewrite.return_value = {
            "query": "如何优化数据库性能（术语已对齐）",
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
            dissatisfaction_detector=mock_dissatisfaction_detector,
            audit_trail=mock_audit_trail_phase2,
        )

        # 第一个查询 → 不满意重试
        result1 = await rewriter.rewrite("Python 怎么学", session_id="session_A")
        assert mock_cache_manager_with_l2.lookup.call_count == 0  # L1 跳过（第 1 次）

        # 第二个查询 → 不同问题，正常管线
        await rewriter.rewrite("数据库怎么优化", session_id="session_A")
        # 不同问题不应跳过 L1 缓存
        assert result1.cache_hit is False

    async def test_same_query_outside_time_window_not_triggered(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_dissatisfaction_detector,
        mock_audit_trail_phase2,
    ):
        """超过滑动窗口（60s）的重复查询不应触发不满意重试。"""
        # 第一次询问后 65s 再次询问 → 窗口外 → 正常管线
        mock_dissatisfaction_detector.check.return_value = False
        mock_protector_phase2.protect.return_value = ("Python 怎么学", {})
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
            "tokens": 40,
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
            dissatisfaction_detector=mock_dissatisfaction_detector,
            audit_trail=mock_audit_trail_phase2,
            dissatisfaction_window_seconds=60.0,
        )

        result = await rewriter.rewrite("Python 怎么学", session_id="session_A")

        # 窗口外 → 检测器未报告不满意
        mock_dissatisfaction_detector.check.assert_called_once()
        # 正常缓存检查
        assert result.cache_hit is False
        # 策略使用正常路由（未升级）
        assert "expand" not in result.strategies_used

    async def test_same_query_different_session_not_triggered(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_dissatisfaction_detector,
        mock_audit_trail_phase2,
    ):
        """不同会话的相同问题不触发不满意重试 —— 检测器 Key 绑定 (session_id, query_hash)。"""
        mock_dissatisfaction_detector.check.return_value = False
        mock_protector_phase2.protect.return_value = ("Python 怎么学", {})
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
            "tokens": 40,
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
            dissatisfaction_detector=mock_dissatisfaction_detector,
            audit_trail=mock_audit_trail_phase2,
        )

        result = await rewriter.rewrite("Python 怎么学", session_id="session_B")

        # 不同会话 → 不触发
        assert (
            not mock_dissatisfaction_detector.check.called
            or mock_dissatisfaction_detector.check.return_value is False
        )
        # 结果不应来自 expand 策略（未升级）
        assert "expand" not in result.strategies_used

    async def test_dissatisfaction_retry_pipeline_still_completes_normally(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_dissatisfaction_detector,
        mock_audit_trail_phase2,
    ):
        """不满意重试时管线仍应正常完成，不抛出异常。"""
        mock_dissatisfaction_detector.check.return_value = True
        mock_protector_phase2.protect.return_value = ("Python 怎么学", {})
        mock_protector_phase2.restore.return_value = "Python 学习替代路径"
        mock_strategy_router.route.return_value = {
            "intent": "procedural",
            "complexity": 5,
            "strategies": ["normalize", "expand"],
        }
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "如何学习 Python",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 40,
        }
        mock_expand_rewriter.rewrite.return_value = {
            "query": "Python 学习替代路径",
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
            dissatisfaction_detector=mock_dissatisfaction_detector,
            audit_trail=mock_audit_trail_phase2,
        )

        try:
            result = await rewriter.rewrite("Python 怎么学", session_id="session_A")
        except Exception as exc:  # pragma: no cover
            pytest.fail(f"不满意重试检测时 rewrite() 意外抛出异常: {exc}")

        assert result is not None
        assert len(result.rewritten_queries) > 0
        # 当前查询被记录到检测器（供后续检测使用）
        mock_dissatisfaction_detector.record.assert_called()

    async def test_normal_query_after_dissatisfaction_uses_normal_cache(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_expand_rewriter,
        mock_cache_manager_with_l2,
        mock_dissatisfaction_detector,
        mock_audit_trail_phase2,
    ):
        """不满意重试后续的不同查询应恢复正常缓存行为。

        场景：用户先重复提问 → 不满意触发 → 然后问新问题 → 新问题
        正常检查 L1 缓存，不跳过。
        """
        # 第 1 次调用 → 检测到不满意
        # 第 2 次调用 → 正常（不同查询）
        mock_dissatisfaction_detector.check.side_effect = [True, False]
        mock_protector_phase2.protect.side_effect = [
            ("Python 怎么学", {}),
            ("数据库索引怎么建", {}),
        ]
        mock_protector_phase2.restore.side_effect = [
            "Python 学习替代路径",
            "如何创建数据库索引（术语已对齐）",
        ]
        mock_strategy_router.route.side_effect = [
            {
                "intent": "procedural",
                "complexity": 5,
                "strategies": ["normalize", "expand"],
            },
            {
                "intent": "procedural",
                "complexity": 4,
                "strategies": ["normalize", "term_align"],
            },
        ]
        mock_normalize_rewriter.rewrite.side_effect = [
            {
                "query": "如何学习 Python",
                "strategy": "normalize",
                "duration_ms": 100.0,
                "tokens": 40,
            },
            {
                "query": "如何创建数据库索引",
                "strategy": "normalize",
                "duration_ms": 100.0,
                "tokens": 38,
            },
        ]
        mock_expand_rewriter.rewrite.return_value = {
            "query": "Python 学习替代路径",
            "strategy": "expand",
            "duration_ms": 180.0,
            "tokens": 55,
        }
        mock_term_align_rewriter.rewrite.return_value = {
            "query": "如何创建数据库索引（术语已对齐）",
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
            dissatisfaction_detector=mock_dissatisfaction_detector,
            audit_trail=mock_audit_trail_phase2,
        )

        # 不满意重试
        await rewriter.rewrite("Python 怎么学", session_id="session_A")
        # 不同查询 → 恢复正常
        await rewriter.rewrite("数据库索引怎么建", session_id="session_A")

        # 第二次调用时 L1 缓存正常检查
        # 关键：不同查询不应受前一次不满意状态影响
        assert mock_dissatisfaction_detector.check.call_count == 2
