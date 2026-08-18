"""AuditTrail 审计日志测试 —— 查询重写的结构化审计日志。

测试覆盖：
- 正常路径：包含所有结构化字段的完整审计事件
- 边界情况：空查询、超长查询、空策略列表
- 异常处理：logger 不可用时的降级兜底
"""

import logging

import pytest
from structlog.testing import capture_logs

# ──────────────────────────────────────────────────────────────────────────────
# 待测类位于 app.services.audit_trail。目前该类尚不存在 —— 这些是红阶段测试，
# 用于驱动 AuditTrail 的实现（TDD 红 → 绿 → 重构循环）。
# ──────────────────────────────────────────────────────────────────────────────

# 尝试导入；如果模块/类尚未创建，则测试在运行时失败（TDD 红阶段）。
# 注意：此处不使用 pytest.mark.skipif —— 项目 TDD 实践中，红阶段测试应显式
# 失败（FAIL）而非跳过（SKIP），与 test_search_service.py / test_search_schema.py
# 保持一致。
try:
    from app.services.audit_trail import AuditTrail
except ImportError:
    AuditTrail = None  # type: ignore[assignment]


# ── 正常路径测试 ──────────────────────────────────────────────────────────────


class TestAuditTrailNormalPath:
    """验证完整审计事件包含所有预期的结构化字段。"""

    def test_records_query_rewrite_complete_event(self):
        """``record('query_rewrite_complete', ...)``
        应输出一个事件名为 query_rewrite_complete 的日志。"""
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record("query_rewrite_complete", trace_id="t-001")
        assert len(cap) == 1
        assert cap[0]["event"] == "query_rewrite_complete"

    def test_trace_id_is_recorded(self):
        """传入的 ``trace_id`` 关键字参数应出现在结构化日志输出中。"""
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record("query_rewrite_complete", trace_id="01JFZ8KJ4X2Q3M5N")
        assert cap[0]["trace_id"] == "01JFZ8KJ4X2Q3M5N"

    def test_original_query_is_recorded(self):
        """用户原始查询文本应作为 ``original_query`` 字段记录。"""
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-002",
                original_query="如何优化 JVM 参数",
            )
        assert cap[0]["original_query"] == "如何优化 JVM 参数"

    def test_query_hash_is_recorded(self):
        """基于 SHA256 的查询哈希应作为 ``query_hash`` 字段记录。"""
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-003",
                query_hash="a1b2c3d4e5f6a7b8",
            )
        assert cap[0]["query_hash"] == "a1b2c3d4e5f6a7b8"

    def test_protected_terms_are_recorded(self):
        """查询中识别出的保护词列表应作为 ``protected_terms`` 记录。"""
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-004",
                protected_terms=["JVM", "K8s", "@Autowired"],
            )
        assert cap[0]["protected_terms"] == ["JVM", "K8s", "@Autowired"]

    def test_context_used_flag_is_recorded(self):
        """是否使用了对话上下文（上下文融合）应作为 ``context_used`` 布尔值记录。"""
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-005",
                context_used=True,
            )
        assert cap[0]["context_used"] is True

    def test_intent_is_recorded(self):
        """分类得到的意图标签应作为 ``intent`` 字段记录。"""
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-006",
                intent="analytical",
            )
        assert cap[0]["intent"] == "analytical"

    def test_complexity_is_recorded(self):
        """复杂度评分（1-10）应作为 ``complexity`` 字段记录。"""
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-007",
                complexity=7,
            )
        assert cap[0]["complexity"] == 7

    def test_strategies_executed_are_recorded(self):
        """实际执行的策略名称列表应作为 ``strategies_executed`` 记录。"""
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-008",
                strategies_executed=["context_fusion", "normalize", "term_align"],
            )
        assert cap[0]["strategies_executed"] == [
            "context_fusion",
            "normalize",
            "term_align",
        ]

    def test_rewrites_list_is_recorded(self):
        """每条改写结果（含 query/strategy/duration_ms/tokens）
        应以字典列表的形式记录在 ``rewrites`` 字段中。"""
        audit = AuditTrail()
        rewrites = [
            {
                "query": "JVM 内存参数如何优化配置",
                "strategy": "context_fusion",
                "duration_ms": 120.5,
                "tokens": 85,
            },
            {
                "query": "JVM 内存参数优化配置方法",
                "strategy": "normalize",
                "duration_ms": 200.3,
                "tokens": 110,
            },
        ]
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-009",
                rewrites=rewrites,
            )
        assert cap[0]["rewrites"] == rewrites

    def test_total_rewrite_time_ms_is_recorded(self):
        """整个重写管线的墙上时钟耗时（毫秒）应作为 ``total_rewrite_time_ms`` 记录。"""
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-010",
                total_rewrite_time_ms=320.8,
            )
        assert cap[0]["total_rewrite_time_ms"] == 320.8

    def test_cache_hit_flag_is_recorded(self):
        """结果是否来自缓存应作为 ``cache_hit`` 布尔值记录。"""
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-011",
                cache_hit=True,
            )
        assert cap[0]["cache_hit"] is True

    def test_cache_level_is_recorded(self):
        """命中缓存的层级（L1 / L2）应作为 ``cache_level`` 记录。"""
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-012",
                cache_level="L2",
            )
        assert cap[0]["cache_level"] == "L2"

    def test_quality_scores_are_recorded(self):
        """质量评估的评分字典应作为 ``quality_scores`` 记录。"""
        audit = AuditTrail()
        scores = {
            "semantic_preservation": 5,
            "clarity_improvement": 4,
            "information_gain": 3,
            "term_accuracy": 5,
            "retrievability": 4,
            "total_score": 21,
            "verdict": "good",
            "issues": [],
        }
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-013",
                quality_scores=scores,
            )
        assert cap[0]["quality_scores"] == scores

    def test_prompt_versions_are_recorded(self):
        """Prompt 版本映射（策略名 → 版本号）应作为 ``prompt_versions`` 记录。"""
        audit = AuditTrail()
        versions = {"intent_classification": "1.2.0", "normalize": "1.0.0"}
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-014",
                prompt_versions=versions,
            )
        assert cap[0]["prompt_versions"] == versions

    def test_llm_calls_are_recorded(self):
        """每次 LLM 调用的详细信息应记录在 ``llm_calls`` 列表中。"""
        audit = AuditTrail()
        calls = [
            {
                "purpose": "intent_classification",
                "model": "qwen3.5-plus",
                "prompt_tokens": 200,
                "completion_tokens": 50,
                "total_tokens": 250,
                "duration_ms": 350.0,
            },
            {
                "purpose": "normalize",
                "model": "qwen3.5-plus",
                "prompt_tokens": 180,
                "completion_tokens": 60,
                "total_tokens": 240,
                "duration_ms": 420.0,
            },
        ]
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-015",
                llm_calls=calls,
            )
        assert cap[0]["llm_calls"] == calls

    def test_complete_audit_event_contains_all_expected_top_level_keys(self):
        """一个完整填充的审计事件应包含所有预期的顶层字段。"""
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="01JFZ8KJ4X2Q3M5N",
                original_query="它怎么配置",
                query_hash="abc123def4567890",
                protected_terms=["Nginx"],
                context_used=True,
                intent="analytical",
                complexity=5,
                strategies_executed=["context_fusion", "normalize"],
                rewrites=[
                    {
                        "query": "Nginx 配置文件如何修改",
                        "strategy": "context_fusion",
                        "duration_ms": 150.0,
                        "tokens": 70,
                    },
                    {
                        "query": "Nginx 配置文件修改方法",
                        "strategy": "normalize",
                        "duration_ms": 200.0,
                        "tokens": 90,
                    },
                ],
                total_rewrite_time_ms=450.0,
                cache_hit=False,
                cache_level=None,
                quality_scores={
                    "semantic_preservation": 5,
                    "clarity_improvement": 4,
                    "information_gain": 3,
                    "term_accuracy": 5,
                    "retrievability": 4,
                    "total_score": 21,
                    "verdict": "good",
                    "issues": [],
                },
                prompt_versions={"intent_classification": "1.2.0", "normalize": "1.0.0"},
                llm_calls=[
                    {
                        "purpose": "intent_classification",
                        "model": "qwen3.5-plus",
                        "prompt_tokens": 150,
                        "completion_tokens": 40,
                        "total_tokens": 190,
                        "duration_ms": 300.0,
                    }
                ],
            )
        event = cap[0]
        assert event["event"] == "query_rewrite_complete"
        assert event["trace_id"] == "01JFZ8KJ4X2Q3M5N"
        assert event["original_query"] == "它怎么配置"
        assert event["query_hash"] == "abc123def4567890"
        assert event["protected_terms"] == ["Nginx"]
        assert event["context_used"] is True
        assert event["intent"] == "analytical"
        assert event["complexity"] == 5
        assert event["strategies_executed"] == ["context_fusion", "normalize"]
        assert len(event["rewrites"]) == 2
        assert event["total_rewrite_time_ms"] == 450.0
        assert event["cache_hit"] is False
        assert event["quality_scores"]["total_score"] == 21
        assert "prompt_versions" in event
        assert "llm_calls" in event

    def test_record_uses_structured_kwargs_not_string_interpolation(self):
        """AuditTrail.record() 通过关键字参数传递结构化字段（遵循项目结构化日志规范），
        而非在事件消息中使用 f-string 或 % 格式化拼接。"""
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-016",
                original_query="test",
            )
        event = cap[0]
        # 事件消息是固定的；所有数据都存在于关键字参数字段中。
        assert event["event"] == "query_rewrite_complete"
        # 验证事件字符串本身不是 f-string 模板拼接的消息。
        # capture_logs 保留了结构化字段；事件消息仅作为键值存在。
        assert event["trace_id"] == "t-016"
        assert event["original_query"] == "test"


# ── 边界情况测试 ──────────────────────────────────────────────────────────────


class TestAuditTrailEdgeCases:
    """边界条件：空输入、截断、空集合。"""

    def test_empty_query_string_is_recorded_as_is(self):
        """空字符串的 original_query 应原样透传，不导致崩溃。"""
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-empty",
                original_query="",
            )
        assert cap[0]["original_query"] == ""

    def test_very_long_query_is_recorded_complete(self):
        """超长查询（SearchRequest 上限为 2000 字符）应由 AuditTrail 完整记录，
        不做截断。截断（如果有）属于调用方的职责。"""
        long_query = "如何" + "优化" * 500  # 约 1000 个字符
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-long",
                original_query=long_query,
            )
        assert cap[0]["original_query"] == long_query

    def test_empty_strategies_executed_list(self):
        """未执行任何策略时，strategies_executed 应为空列表。"""
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-no-strategies",
                strategies_executed=[],
            )
        assert cap[0]["strategies_executed"] == []

    def test_empty_rewrites_list(self):
        """未产生任何改写结果时，rewrites 应为空列表。"""
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-no-rewrites",
                rewrites=[],
            )
        assert cap[0]["rewrites"] == []

    def test_none_cache_level(self):
        """未命中缓存时，cache_level 应为 None。"""
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-no-cache",
                cache_hit=False,
                cache_level=None,
            )
        assert cap[0]["cache_level"] is None

    def test_empty_protected_terms_list(self):
        """未找到保护词时，protected_terms 应为空列表。"""
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-no-protected",
                protected_terms=[],
            )
        assert cap[0]["protected_terms"] == []

    def test_empty_prompt_versions_dict(self):
        """未显式配置 Prompt 版本时，prompt_versions 应为空字典。"""
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-no-versions",
                prompt_versions={},
            )
        assert cap[0]["prompt_versions"] == {}

    def test_unicode_query_with_emoji_and_special_chars(self):
        """包含 emoji 和特殊字符的查询应被正确记录。"""
        query = "Python 🐍 性能优化 〜 メモリ管理 🔧"
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-unicode",
                original_query=query,
            )
        assert cap[0]["original_query"] == query

    def test_none_intent_and_complexity(self):
        """未进行意图/复杂度分类时，intent 和 complexity 应为 None。"""
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-no-intent",
                intent=None,
                complexity=None,
            )
        assert cap[0]["intent"] is None
        assert cap[0]["complexity"] is None


# ── 异常处理 / 降级测试 ───────────────────────────────────────────────────────


class TestAuditTrailErrorHandling:
    """验证在日志基础设施异常时 AuditTrail 不会崩溃。"""

    def test_record_does_not_raise_on_unknown_kwargs(self, caplog):
        """传入未显式声明的额外关键字参数不应导致崩溃，
        而是应被透传给 structlog。"""
        audit = AuditTrail()
        caplog.set_level(logging.INFO)
        # 不应抛出异常。
        audit.record(
            "query_rewrite_complete",
            trace_id="t-extra",
            extra_unknown_field="should_be_forwarded",
        )
        assert "query_rewrite_complete" in caplog.text

    def test_record_does_not_raise_when_caplog_handler_is_missing(self):
        """当没有配置 structlog 兼容的 handler 时（无 capture_logs 上下文），
        record() 调用不应抛出异常。structlog 应静默丢弃事件或路由到兜底 handler。"""
        audit = AuditTrail()
        # 无 capture_logs 上下文 —— 测试环境中 structlog 可能没有配置
        # 任何处理器。此调用仍必须成功。
        try:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-no-handler",
                original_query="test",
            )
        except Exception as exc:  # pragma: no cover —— 预期无异常
            pytest.fail(f"AuditTrail.record() 意外抛出异常: {exc}")

    def test_record_with_only_event_name(self):
        """仅传入事件名称（不传额外字段）时不应崩溃。"""
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record("query_rewrite_complete")
        assert len(cap) == 1
        assert cap[0]["event"] == "query_rewrite_complete"

    def test_record_with_non_serializable_value_does_not_crash(self):
        """传入不可 JSON 序列化的对象作为字段值时，调用不应崩溃。
        （structlog 的 JSONRenderer 可能在后续渲染时失败，
        但 record() 调用本身应安全无虞。）"""
        audit = AuditTrail()

        class _NonSerializable:
            pass

        with capture_logs() as cap:
            audit.record(
                "query_rewrite_complete",
                trace_id="t-nonserial",
                non_serializable=_NonSerializable(),
            )
        # record 调用本身成功；structlog 可能在后续渲染时将其字符串化或失败，
        # 但 AuditTrail 本身不应抛出异常。
        assert cap[0]["event"] == "query_rewrite_complete"
        # 不可序列化的值按原样存在于事件字典中。
        assert "non_serializable" in cap[0]

    def test_record_allows_multiple_events_in_sequence(self):
        """连续的多次 record() 调用每次都应产生一条日志事件。"""
        audit = AuditTrail()
        with capture_logs() as cap:
            audit.record("query_rewrite_start", trace_id="t-seq")
            audit.record("query_rewrite_complete", trace_id="t-seq")
        assert len(cap) == 2
        assert cap[0]["event"] == "query_rewrite_start"
        assert cap[1]["event"] == "query_rewrite_complete"
