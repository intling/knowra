"""QueryRewriter 顶层编排器测试 —— 查询重写管线的集成与编排。

测试覆盖：
- 正常路径：完整管线执行（精确词保护 → L1 缓存查询 → 请求去重 →
  上下文融合 → 保护词还原 → 缓存写入 → 审计日志）
- 条件触发：无指代词时跳过上下文融合、无保护词时跳过保护/还原
- 缓存命中：L1 命中直接返回，跳过 LLM 调用
- 降级场景：LLM 调用失败静默降级返回原始查询、管线超时降级
- 模块开关：QUERY_REWRITE_ENABLED=false 时跳过重写
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from app.services.query_rewriter import QueryRewriter, RewriteResult

# ── 共享 fixture 与辅助函数 ──────────────────────────────────


@pytest.fixture
def mock_protector() -> MagicMock:
    """Mock ExactTermProtector —— 默认透传查询，无保护词。"""
    protector = MagicMock()
    protector.protect.return_value = ("test query", {})
    protector.restore.return_value = "test query"
    return protector


@pytest.fixture
def mock_context_rewriter() -> MagicMock:
    """Mock ContextRewriter —— 默认返回融合后的查询。"""
    rewriter = MagicMock()
    rewriter.rewrite.return_value = "rewritten query with context"
    return rewriter


@pytest.fixture
def mock_cache_manager() -> MagicMock:
    """Mock CacheManager —— 默认缓存未命中。

    lookup(session_id, query_hash) 签名，store(session_id, query_hash, result) 签名。
    """
    cache = MagicMock()
    cache.lookup.return_value = None
    return cache


@pytest.fixture
def mock_audit_trail() -> MagicMock:
    """Mock AuditTrail —— 静默记录，不做实际日志输出。"""
    return MagicMock()


@pytest.fixture
def mock_chat_adapter_fixture() -> MagicMock:
    """ChatAdapter mock fixture，避免与 conftest 命名冲突。"""
    from types import SimpleNamespace

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


def _build_rewriter(
    protector=None,
    context_rewriter=None,
    cache_manager=None,
    chat_adapter=None,
    audit_trail=None,
    *,
    enabled: bool = True,
    pipeline_timeout: float = 3.0,
) -> QueryRewriter:
    """构建 QueryRewriter 实例的辅助函数。"""
    protector = protector or MagicMock()
    context_rewriter = context_rewriter or MagicMock()
    cache_manager = cache_manager or MagicMock()
    chat_adapter = chat_adapter or MagicMock()
    audit_trail = audit_trail or MagicMock()
    return QueryRewriter(
        exact_term_protector=protector,
        context_rewriter=context_rewriter,
        cache_manager=cache_manager,
        chat_adapter=chat_adapter,
        audit_trail=audit_trail,
        enabled=enabled,
        pipeline_timeout=pipeline_timeout,
    )


def _rewrite_result(
    *,
    original_query: str = "test query",
    rewritten_queries: list[dict] | None = None,
    strategies_used: list[str] | None = None,
    rewrite_time_ms: float = 0.0,
    cache_hit: bool = False,
    rewrite_model: str | None = None,
) -> RewriteResult:
    """构建 RewriteResult 实例的辅助函数。"""
    return RewriteResult(
        original_query=original_query,
        rewritten_queries=rewritten_queries or [{"query": original_query, "strategy": "direct"}],
        strategies_used=strategies_used or [],
        rewrite_time_ms=rewrite_time_ms,
        cache_hit=cache_hit,
        rewrite_model=rewrite_model,
    )


# ══════════════════════════════════════════════════════════
# 正常路径测试
# ══════════════════════════════════════════════════════════


class TestQueryRewriterNormalPath:
    """验证完整管线按正确顺序执行各组件。"""

    pytestmark = pytest.mark.asyncio

    async def test_full_pipeline_executes_in_correct_order(
        self,
        mock_protector,
        mock_context_rewriter,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """完整管线：protect→cache→context rewrite→restore→store→audit。"""
        mock_protector.protect.return_value = (
            "它 [[TERM_0]] 怎么用",
            {0: "Python"},
        )
        mock_protector.restore.return_value = "Python 如何使用"
        mock_context_rewriter.rewrite.return_value = "Python 如何使用"
        mock_cache_manager.lookup.return_value = None

        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=mock_context_rewriter,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
        )

        result = await rewriter.rewrite(
            "Python 怎么用",
            history=[{"role": "user", "content": "Python 是什么"}],
        )

        mock_protector.protect.assert_called_once_with("Python 怎么用")
        mock_cache_manager.lookup.assert_called_once()
        mock_context_rewriter.rewrite.assert_called_once()
        mock_protector.restore.assert_called_once()
        mock_cache_manager.store.assert_called_once()
        mock_audit_trail.record.assert_called()

        assert result.original_query == "Python 怎么用"
        assert len(result.rewritten_queries) >= 1
        assert result.cache_hit is False

    async def test_rewrite_result_contains_all_expected_fields(
        self,
        mock_protector,
        mock_context_rewriter,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """RewriteResult 包含所有预期字段。"""
        mock_protector.protect.return_value = ("它怎么用", {})
        mock_protector.restore.return_value = "Python 如何使用"
        mock_context_rewriter.rewrite.return_value = "Python 如何使用"
        mock_cache_manager.lookup.return_value = None

        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=mock_context_rewriter,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
        )

        result = await rewriter.rewrite("它怎么用", history=None)

        assert isinstance(result.original_query, str)
        assert isinstance(result.rewritten_queries, list)
        assert isinstance(result.strategies_used, list)
        assert isinstance(result.rewrite_time_ms, (int, float))
        assert result.rewrite_time_ms >= 0
        assert isinstance(result.cache_hit, bool)

    async def test_protected_terms_are_restored_after_rewrite(
        self,
        mock_protector,
        mock_context_rewriter,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """保护词在改写完成后被还原为原始术语。"""
        mock_protector.protect.return_value = (
            "这个 [[TERM_0]] 怎么配置",
            {0: "Nginx"},
        )
        mock_protector.restore.return_value = "Nginx 如何配置"
        mock_context_rewriter.rewrite.return_value = "[[TERM_0]] 如何配置"
        mock_cache_manager.lookup.return_value = None

        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=mock_context_rewriter,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
        )

        result = await rewriter.rewrite(
            "Nginx 怎么配置",
            history=[{"role": "user", "content": "Nginx 是什么"}],
        )

        mock_protector.restore.assert_called_once_with("[[TERM_0]] 如何配置", {0: "Nginx"})
        assert result.rewritten_queries[0]["query"] == "Nginx 如何配置"

    async def test_context_fusion_with_history(
        self,
        mock_protector,
        mock_context_rewriter,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """提供对话历史且查询含指代词时应执行上下文融合。"""
        mock_protector.protect.return_value = ("它怎么配置", {})
        mock_protector.restore.return_value = "Nginx 如何配置"
        mock_context_rewriter.rewrite.return_value = "Nginx 如何配置"
        mock_cache_manager.lookup.return_value = None

        history = [
            {"role": "user", "content": "Nginx 怎么安装"},
            {"role": "assistant", "content": "apt-get install nginx..."},
        ]

        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=mock_context_rewriter,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
        )

        _ = await rewriter.rewrite("它怎么配置", history=history)

        mock_context_rewriter.rewrite.assert_called_once()
        call_args = mock_context_rewriter.rewrite.call_args
        assert call_args[1].get("history") == history or call_args[0][1] == history

    async def test_audit_log_is_recorded_on_successful_rewrite(
        self,
        mock_protector,
        mock_context_rewriter,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """成功完成重写后应记录审计日志。"""
        mock_protector.protect.return_value = ("test query", {})
        mock_protector.restore.return_value = "rewritten test query"
        mock_context_rewriter.rewrite.return_value = "rewritten test query"
        mock_cache_manager.lookup.return_value = None

        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=mock_context_rewriter,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
        )

        await rewriter.rewrite("test query", history=None)

        mock_audit_trail.record.assert_called()
        call_kwargs = mock_audit_trail.record.call_args[1]
        assert "original_query" in call_kwargs
        assert "rewrites" in call_kwargs
        assert "total_rewrite_time_ms" in call_kwargs


# ══════════════════════════════════════════════════════════
# 条件触发测试
# ══════════════════════════════════════════════════════════


class TestQueryRewriterConditionalTriggers:
    """验证条件性步骤仅在有需求时触发。"""

    pytestmark = pytest.mark.asyncio

    async def test_skip_context_fusion_when_no_pronouns(
        self,
        mock_protector,
        mock_context_rewriter,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """查询不含指代词时应跳过上下文融合。"""
        mock_protector.protect.return_value = ("如何配置 Nginx 反向代理", {})
        mock_protector.restore.return_value = "如何配置 Nginx 反向代理"
        mock_cache_manager.lookup.return_value = None

        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=mock_context_rewriter,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
        )

        result = await rewriter.rewrite("如何配置 Nginx 反向代理", history=None)

        mock_context_rewriter.rewrite.assert_not_called()
        assert result.rewritten_queries[0]["query"] == "如何配置 Nginx 反向代理"

    async def test_skip_protect_and_restore_when_no_protected_terms(
        self,
        mock_protector,
        mock_context_rewriter,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """不包含保护词时，protect/restore 透传空映射。"""
        mock_protector.protect.return_value = ("普通查询", {})
        mock_protector.restore.return_value = "普通查询"
        mock_cache_manager.lookup.return_value = None

        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=mock_context_rewriter,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
        )

        _ = await rewriter.rewrite("普通查询", history=None)

        mock_protector.protect.assert_called_once()
        mock_protector.restore.assert_called_once()

    async def test_context_fusion_with_no_history_is_skipped(
        self,
        mock_protector,
        mock_context_rewriter,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """对话历史为 None 且查询无指代词时完全跳过上下文融合。"""
        mock_protector.protect.return_value = ("如何优化数据库性能", {})
        mock_protector.restore.return_value = "如何优化数据库性能"
        mock_cache_manager.lookup.return_value = None

        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=mock_context_rewriter,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
        )

        await rewriter.rewrite("如何优化数据库性能", history=None)

        mock_context_rewriter.rewrite.assert_not_called()


# ══════════════════════════════════════════════════════════
# 缓存命中测试
# ══════════════════════════════════════════════════════════


class TestQueryRewriterCacheHit:
    """验证 L1 缓存命中时跳过 LLM 调用直接返回。"""

    pytestmark = pytest.mark.asyncio

    async def test_l1_cache_hit_returns_cached_result_directly(
        self,
        mock_protector,
        mock_context_rewriter,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """L1 精确缓存命中时应直接返回缓存结果。"""
        cached = _rewrite_result(
            original_query="如何优化 JVM 参数",
            rewritten_queries=[
                {"query": "JVM 参数如何优化配置", "strategy": "context_fusion"},
                {"query": "JVM 参数优化配置方法", "strategy": "normalize"},
            ],
            strategies_used=["context_fusion", "normalize"],
            rewrite_time_ms=0.5,
            cache_hit=True,
        )
        mock_cache_manager.lookup.return_value = cached

        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=mock_context_rewriter,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
        )

        result = await rewriter.rewrite("如何优化 JVM 参数", history=None)

        assert result.cache_hit is True
        assert result.rewrite_time_ms == 0.5
        assert len(result.rewritten_queries) == 2
        assert result.strategies_used == ["context_fusion", "normalize"]
        mock_context_rewriter.rewrite.assert_not_called()
        mock_chat_adapter_fixture.generate.assert_not_called()

    async def test_l1_cache_hit_still_records_audit_log(
        self,
        mock_protector,
        mock_context_rewriter,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """缓存命中时仍应记录审计日志。"""
        cached = _rewrite_result(
            original_query="test",
            cache_hit=True,
            rewrite_time_ms=0.3,
        )
        mock_cache_manager.lookup.return_value = cached
        mock_protector.protect.return_value = ("test", {})

        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=mock_context_rewriter,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
        )

        await rewriter.rewrite("test", history=None)

        mock_audit_trail.record.assert_called()
        audit_kwargs = mock_audit_trail.record.call_args[1]
        assert audit_kwargs.get("cache_hit") is True


# ══════════════════════════════════════════════════════════
# 降级场景测试
# ══════════════════════════════════════════════════════════


class TestQueryRewriterDegradation:
    """验证 LLM 失败和超时时静默降级。"""

    pytestmark = pytest.mark.asyncio

    async def test_llm_call_failure_returns_original_query(
        self,
        mock_protector,
        mock_context_rewriter,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """LLM 调用抛出异常时，捕获并静默降级返回原始查询。"""
        from app.services.chat_adapter import ChatAPIError

        mock_protector.protect.return_value = ("test query", {})
        mock_context_rewriter.rewrite.side_effect = ChatAPIError("API connection timeout")
        mock_cache_manager.lookup.return_value = None

        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=mock_context_rewriter,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
        )

        result = await rewriter.rewrite("test query", history=None)

        assert result.original_query == "test query"
        assert result.rewritten_queries[0]["query"] == "test query"
        assert result.cache_hit is False
        mock_audit_trail.record.assert_called()

    async def test_llm_call_failure_does_not_raise_exception(
        self,
        mock_protector,
        mock_context_rewriter,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """LLM 调用失败时 rewrite() 不向调用方抛出异常。"""
        mock_protector.protect.return_value = ("test query", {})
        mock_context_rewriter.rewrite.side_effect = RuntimeError("Unexpected LLM error")
        mock_cache_manager.lookup.return_value = None

        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=mock_context_rewriter,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
        )

        try:
            result = await rewriter.rewrite("test query", history=None)
        except Exception as exc:  # pragma: no cover
            pytest.fail(f"rewrite() 意外抛出异常: {exc}")

        assert result is not None
        assert result.original_query == "test query"

    async def test_pipeline_timeout_returns_original_query(
        self,
        mock_protector,
        mock_context_rewriter,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """管线总超时后应返回原始查询。"""
        mock_protector.protect.return_value = ("test query", {})
        mock_cache_manager.lookup.return_value = None

        async def _slow_rewrite(*args, **kwargs):
            await asyncio.sleep(5.0)
            return "slow result"

        mock_context_rewriter.rewrite.side_effect = _slow_rewrite

        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=mock_context_rewriter,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
            pipeline_timeout=0.1,
        )

        result = await rewriter.rewrite("test query", history=None)

        assert result.original_query == "test query"

    async def test_pipeline_timeout_still_completes_without_error(
        self,
        mock_protector,
        mock_context_rewriter,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """超时降级不应抛出异常。"""
        mock_protector.protect.return_value = ("test query", {})
        mock_cache_manager.lookup.return_value = None
        mock_context_rewriter.rewrite.side_effect = TimeoutError

        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=mock_context_rewriter,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
            pipeline_timeout=3.0,
        )

        try:
            result = await rewriter.rewrite("test query", history=None)
        except Exception as exc:  # pragma: no cover
            pytest.fail(f"超时场景下 rewrite() 意外抛出异常: {exc}")

        assert result is not None


# ══════════════════════════════════════════════════════════
# 模块开关测试
# ══════════════════════════════════════════════════════════


class TestQueryRewriterModuleSwitch:
    """验证 QUERY_REWRITE_ENABLED=false 时完全跳过重写。"""

    pytestmark = pytest.mark.asyncio

    async def test_disabled_module_skips_all_rewriting(
        self,
        mock_protector,
        mock_context_rewriter,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """QUERY_REWRITE_ENABLED=false 时所有重写组件不被调用。"""
        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=mock_context_rewriter,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
            enabled=False,
        )

        result = await rewriter.rewrite("test query", history=None)

        mock_protector.protect.assert_not_called()
        mock_context_rewriter.rewrite.assert_not_called()
        mock_cache_manager.lookup.assert_not_called()
        mock_cache_manager.store.assert_not_called()

        assert result.original_query == "test query"
        assert result.rewritten_queries[0]["query"] == "test query"
        assert result.rewrite_time_ms == 0.0
        assert result.cache_hit is False

    async def test_disabled_module_returns_empty_strategies(
        self,
        mock_protector,
        mock_context_rewriter,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """禁用时 strategies_used 为空列表。"""
        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=mock_context_rewriter,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
            enabled=False,
        )

        result = await rewriter.rewrite("any query", history=None)

        assert result.strategies_used == []

    async def test_enabled_module_executes_normally(
        self,
        mock_protector,
        mock_context_rewriter,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """enabled=True 时模块正常执行。"""
        mock_protector.protect.return_value = ("test query", {})
        mock_protector.restore.return_value = "test query"
        mock_cache_manager.lookup.return_value = None

        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=mock_context_rewriter,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
            enabled=True,
        )

        result = await rewriter.rewrite("test query", history=None)

        mock_protector.protect.assert_called_once()
        assert result is not None


# ══════════════════════════════════════════════════════════
# 请求去重测试
# ══════════════════════════════════════════════════════════


class TestQueryRewriterDeduplication:
    """验证并发请求去重。"""

    pytestmark = pytest.mark.asyncio

    async def test_concurrent_identical_queries_share_result(
        self,
        mock_protector,
        mock_context_rewriter,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """并发相同查询共享重写结果，不重复调用 LLM。"""
        call_count = 0

        async def _counted_rewrite(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            return "rewritten query"

        mock_protector.protect.return_value = ("它 shared query", {})
        mock_protector.restore.return_value = "rewritten query"
        mock_context_rewriter.rewrite.side_effect = _counted_rewrite
        mock_cache_manager.lookup.return_value = None

        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=mock_context_rewriter,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
        )

        async def _rewrite():
            return await rewriter.rewrite(
                "它 shared query", history=[{"role": "user", "content": "hi"}]
            )

        results = await asyncio.gather(_rewrite(), _rewrite(), _rewrite())

        assert call_count == 1
        first_q = results[0].rewritten_queries[0]["query"]
        assert all(r.rewritten_queries[0]["query"] == first_q for r in results)


# ══════════════════════════════════════════════════════════
# RewriteResult 模型测试（同步，不涉及 IO）
# ══════════════════════════════════════════════════════════


class TestRewriteResultModel:
    """验证 RewriteResult 数据模型的字段与默认值。"""

    def test_rewrite_result_fields_and_defaults(self):
        """RewriteResult 应具有正确的字段和默认值。"""
        result = RewriteResult(original_query="test")

        assert result.original_query == "test"
        assert result.rewritten_queries == []
        assert result.strategies_used == []
        assert result.rewrite_time_ms == 0.0
        assert result.cache_hit is False

    def test_rewrite_result_with_full_data(self):
        """RewriteResult 接受完整数据时正确存储所有字段。"""
        rewritten_queries = [
            {"query": "Python 如何使用", "strategy": "context_fusion"},
            {"query": "Python 使用方法", "strategy": "normalize"},
        ]
        result = RewriteResult(
            original_query="它怎么用",
            rewritten_queries=rewritten_queries,
            strategies_used=["context_fusion", "normalize"],
            rewrite_time_ms=450.5,
            cache_hit=False,
        )

        assert result.original_query == "它怎么用"
        assert result.rewritten_queries == rewritten_queries
        assert result.strategies_used == ["context_fusion", "normalize"]
        assert result.rewrite_time_ms == 450.5
        assert result.cache_hit is False

    def test_rewrite_result_rewrite_time_ms_must_be_non_negative(self):
        """rewrite_time_ms 不应接受负值。"""
        with pytest.raises(ValueError):
            RewriteResult(original_query="test", rewrite_time_ms=-1.0)


# ══════════════════════════════════════════════════════════
# 会话绑定缓存测试（模块一）
# ══════════════════════════════════════════════════════════


class TestSessionScopedCache:
    """验证缓存键绑定会话 ID，不同会话的相同查询不共享缓存。"""

    pytestmark = pytest.mark.asyncio

    async def test_different_sessions_same_query_cache_isolated(
        self,
        mock_protector,
        mock_context_rewriter,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """不同 session_id 的相同查询应使用各自的缓存条目。"""
        mock_protector.protect.return_value = ("Python 怎么学", {})
        mock_protector.restore.return_value = "Python 如何学习"
        mock_context_rewriter.rewrite.return_value = "Python 如何学习"
        mock_cache_manager.lookup.return_value = None

        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=mock_context_rewriter,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
        )

        # 会话 A 查询
        await rewriter.rewrite("Python 怎么学", session_id="session_a", history=None)
        # 会话 B 相同查询
        await rewriter.rewrite("Python 怎么学", session_id="session_b", history=None)

        # 两次 lookup 使用了不同的 session_id
        assert mock_cache_manager.lookup.call_count == 2
        call_args_list = mock_cache_manager.lookup.call_args_list
        assert call_args_list[0][0][0] == "session_a"  # 第一个参数是 session_id
        assert call_args_list[1][0][0] == "session_b"

        # 两次 store 使用了不同的 session_id
        assert mock_cache_manager.store.call_count == 2
        store_args_list = mock_cache_manager.store.call_args_list
        assert store_args_list[0][0][0] == "session_a"
        assert store_args_list[1][0][0] == "session_b"

    async def test_same_session_same_query_cache_hit(
        self,
        mock_protector,
        mock_context_rewriter,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """同一 session_id 的相同查询（非连续）应命中缓存。"""
        cached = _rewrite_result(
            original_query="Python 怎么学",
            rewritten_queries=[{"query": "Python 如何学习", "strategy": "direct"}],
            cache_hit=True,
        )
        mock_cache_manager.lookup.return_value = cached

        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=mock_context_rewriter,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
        )

        result = await rewriter.rewrite("Python 怎么学", session_id="session_a", history=None)

        assert result.cache_hit is True
        mock_cache_manager.lookup.assert_called_once()

    async def test_query_exact_match_same_hash(
        self,
        mock_protector,
        mock_context_rewriter,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """相同查询文本（逐字符一致）应产生相同的 query_hash（精确匹配）。"""
        mock_protector.protect.return_value = ("Python 怎么学", {})
        mock_protector.restore.return_value = "Python 怎么学"
        mock_cache_manager.lookup.return_value = None

        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=mock_context_rewriter,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
        )

        # 完全相同的查询文本
        await rewriter.rewrite("Python 怎么学", session_id="sess", history=None)
        await rewriter.rewrite("Python 怎么学", session_id="sess", history=None)

        # 两次 lookup 的 query_hash 应相同（原始文本一致）
        assert mock_cache_manager.lookup.call_count == 2
        hash1 = mock_cache_manager.lookup.call_args_list[0][0][1]
        hash2 = mock_cache_manager.lookup.call_args_list[1][0][1]
        assert hash1 == hash2

    async def test_different_query_different_hash(
        self,
        mock_protector,
        mock_context_rewriter,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """不同空白或不同内容的查询产生不同的 query_hash（无规范化）。"""
        mock_protector.protect.return_value = ("Python 怎么学", {})
        mock_protector.restore.return_value = "Python 怎么学"
        mock_cache_manager.lookup.return_value = None

        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=mock_context_rewriter,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
        )

        # 不同空白 → 不同原始文本 → 不同哈希
        q1 = "Python  怎么学"
        q2 = "  Python 怎么学  "

        await rewriter.rewrite(q1, session_id="sess", history=None)
        await rewriter.rewrite(q2, session_id="sess", history=None)

        assert mock_cache_manager.lookup.call_count == 2
        hash1 = mock_cache_manager.lookup.call_args_list[0][0][1]
        hash2 = mock_cache_manager.lookup.call_args_list[1][0][1]
        assert hash1 != hash2

    async def test_session_id_derived_from_history(
        self,
        mock_protector,
        mock_context_rewriter,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """session_id=None 时应从 history 自动派生。"""
        mock_protector.protect.return_value = ("它怎么配", {})
        mock_protector.restore.return_value = "Nginx 怎么配"
        mock_context_rewriter.rewrite.return_value = "Nginx 怎么配"
        mock_cache_manager.lookup.return_value = None

        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=mock_context_rewriter,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
        )

        history_a = [{"role": "user", "content": "Nginx 是什么"}]
        history_b = [{"role": "user", "content": "Python 是什么"}]

        await rewriter.rewrite("它怎么配", session_id=None, history=history_a)
        await rewriter.rewrite("它怎么配", session_id=None, history=history_b)

        # 不同 history → 不同 session_id → 不同缓存
        assert mock_cache_manager.lookup.call_count == 2
        sid_hash_1 = mock_cache_manager.lookup.call_args_list[0][0][0]
        sid_hash_2 = mock_cache_manager.lookup.call_args_list[1][0][0]
        assert sid_hash_1 != sid_hash_2


# ══════════════════════════════════════════════════════════
# Session ID 派生测试
# ══════════════════════════════════════════════════════════


class TestSessionIdDerivation:
    """验证从对话历史派生 session_id 的逻辑。"""

    def test_no_history_returns_default(self):
        """无历史时返回默认 session_id。"""
        sid = QueryRewriter._derive_session_id(None)
        assert sid == "__default__"

    def test_empty_history_returns_default(self):
        """空历史列表时返回默认 session_id。"""
        sid = QueryRewriter._derive_session_id([])
        assert sid == "__default__"

    def test_same_history_same_session_id(self):
        """相同历史内容产生相同 session_id。"""
        history = [{"role": "user", "content": "你好"}]
        sid1 = QueryRewriter._derive_session_id(history)
        sid2 = QueryRewriter._derive_session_id(history)
        assert sid1 == sid2

    def test_different_history_different_session_id(self):
        """不同历史内容产生不同 session_id。"""
        h1 = [{"role": "user", "content": "Nginx 配置"}]
        h2 = [{"role": "user", "content": "Python 语法"}]
        assert QueryRewriter._derive_session_id(h1) != QueryRewriter._derive_session_id(h2)

    def test_filters_non_user_assistant_roles(self):
        """仅对 user/assistant 角色的消息进行哈希。"""
        h1 = [{"role": "user", "content": "hi"}, {"role": "system", "content": "ignore"}]
        h2 = [{"role": "user", "content": "hi"}, {"role": "system", "content": "different"}]
        # system 消息被过滤，所以相同
        assert QueryRewriter._derive_session_id(h1) == QueryRewriter._derive_session_id(h2)
