"""QueryRewriter 顶层编排器 —— 查询重写管线的集成与编排。

Phase 1 管线流程：
    L1 缓存查询 → 请求去重 → 精确词保护 → 上下文融合（条件触发）
    → 保护词还原 → 写入 L1 缓存 → 审计日志记录

会话绑定缓存（模块一）：
    - 缓存 Key 绑定会话 ID，不同会话的相同问题不共享缓存
    - 精确匹配：原始 Query 字符串逐字符完全一致时命中

Usage::

    rewriter = QueryRewriter(
        exact_term_protector=protector,
        context_rewriter=context_rewriter,
        cache_manager=cache_manager,
        chat_adapter=chat_adapter,
        audit_trail=audit_trail,
    )
    result = await rewriter.rewrite("它怎么用", session_id="sess_abc", history=[...])
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import time
from dataclasses import dataclass, field, replace

from app.core.logging import get_logger
from app.services.chat_adapter import ChatAPIError

# ── 中文指代词集合 ─────────────────────────────────────────────────────────
# 用于判断查询是否依赖对话上下文（需触发上下文融合）。

_PRONOUNS = frozenset(
    {
        # 人称 / 指物代词
        "它",
        "他",
        "她",
        "这个",
        "那个",
        "这些",
        "那些",
        "其",
        "此",
        "该",
        "它们",
        "他们",
        "她们",
        # 上下文指代短语（依赖对话历史才能消歧）
        "上文",
        "前面",
        "上述",
        "刚才",
        "之前",
        "以上",
    }
)



# ── RewriteResult ──────────────────────────────────────────────────────────


@dataclass
class RewriteResult:
    """一次查询重写的完整结果。

    Attributes:
        original_query: 用户原始查询文本。
        rewritten_queries: 改写后的查询列表，每条为 ``{"query": str, "strategy": str}``。
        strategies_used: 本次实际执行的策略名称列表。
        rewrite_time_ms: 重写耗时（毫秒）。
        cache_hit: 结果是否来自缓存命中。
    """

    original_query: str
    rewritten_queries: list[dict] = field(default_factory=list)
    strategies_used: list[str] = field(default_factory=list)
    rewrite_time_ms: float = 0.0
    cache_hit: bool = False
    rewrite_model: str | None = None

    def __post_init__(self) -> None:
        if self.rewrite_time_ms < 0:
            raise ValueError(f"rewrite_time_ms must be >= 0, got {self.rewrite_time_ms}")


# ── QueryRewriter ──────────────────────────────────────────────────────────


class QueryRewriter:
    """查询重写顶层编排器。

    组合 ExactTermProtector、ContextRewriter、CacheManager、AuditTrail，
    通过 ``rewrite(query, session_id, history)`` 单一入口执行完整重写管线。

    管线顺序（Phase 1）：
        L1 缓存查询（会话绑定）→ 请求去重 → 精确词保护 → 上下文融合（条件触发）
        → 保护词还原 → 写入 L1 缓存 → 审计日志记录

    会话绑定缓存：
        缓存 Key = session_id + query_hash（原始查询文本），不同会话的相同查询
        不共享缓存结果。

    LLM 调用失败或管线超时时静默降级，返回原始查询确保搜索流程不中断。
    """

    def __init__(
        self,
        *,
        exact_term_protector: object,
        context_rewriter: object,
        cache_manager: object,
        chat_adapter: object,
        audit_trail: object,
        enabled: bool = True,
        pipeline_timeout: float = 3.0,
    ) -> None:
        self._protector = exact_term_protector
        self._context_rewriter = context_rewriter
        self._cache_manager = cache_manager
        self._chat_adapter = chat_adapter
        self._audit_trail = audit_trail
        self._enabled = enabled
        self._pipeline_timeout = pipeline_timeout

        self._logger = get_logger(__name__)

        # 请求去重：in-flight 查询追踪
        self._inflight: dict[str, asyncio.Event] = {}
        self._inflight_results: dict[str, RewriteResult] = {}

    # ── helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _hash_query(query: str) -> str:
        """对查询文本计算 SHA-256 哈希前缀。

        返回 16 字符十六进制哈希，用于缓存键。直接对原始查询文本哈希，
        不做任何规范化处理 —— 相同字符串（逐字符一致）才会产生相同哈希。
        """
        return hashlib.sha256(query.encode()).hexdigest()[:16]

    @staticmethod
    def _derive_session_id(history: list[dict] | None) -> str:
        """从对话历史派生会话标识符。

        当外部未提供 session_id 时，通过对历史中的 user/assistant 消息序列
        进行哈希来生成一个稳定的会话标识。同一对话的不同轮次会产生相同的
        session_id（只要历史序列前缀一致）。

        无历史时返回固定默认值 ``"__default__"``。
        """
        if not history:
            return "__default__"

        normalized = [
            f"{msg.get('role', '')}:{msg.get('content', '')}"
            for msg in history
            if msg.get("role") in ("user", "assistant")
        ]
        if not normalized:
            return "__default__"

        return hashlib.sha256("|".join(normalized).encode()).hexdigest()[:16]

    def _resolve_model(self, rewrite_model: str | None) -> str:
        """Resolve the effective rewrite model, falling back to the configured default."""
        return rewrite_model or self._chat_adapter.config.model  # type: ignore[union-attr]

    # ── public API ──────────────────────────────────────────────────────

    async def rewrite(
        self,
        query: str,
        session_id: str | None = None,
        history: list[dict] | None = None,
        *,
        rewrite_model: str | None = None,
    ) -> RewriteResult:
        """执行查询重写管线，返回 RewriteResult。

        Args:
            query: 用户原始查询文本。
            session_id: 会话标识符。为 None 时从 history 自动派生。
                        用于会话绑定缓存。
            history: 可选的多轮对话历史（role + content 消息列表）。
            rewrite_model: 可选的重写模型覆盖。为 ``None`` 时使用配置的默认模型。

        Returns:
            RewriteResult 包含原始查询、改写结果列表、策略、耗时与缓存状态。

        Raises:
            不抛出异常 —— 所有失败场景均静默降级为原始查询透传。
        """
        # 解析有效模型（None 时回退到配置默认值）
        effective_model = self._resolve_model(rewrite_model)

        # 解析会话 ID：显式传入优先，否则从 history 派生
        resolved_session_id = session_id or self._derive_session_id(history)

        # 模块开关
        if not self._enabled:
            return RewriteResult(
                original_query=query,
                rewritten_queries=[{"query": query, "strategy": "direct"}],
                rewrite_model=effective_model,
            )

        # ── 查询哈希（直接对原始查询文本哈希，用于精确匹配缓存）──
        query_hash = self._hash_query(query)

        # ── L1 缓存：会话绑定查找 ──
        cached = self._cache_manager.lookup(  # type: ignore[union-attr]
            resolved_session_id, query_hash
        )
        if cached is not None:
            result = replace(cached, cache_hit=True)
            self._audit_trail.record(  # type: ignore[union-attr]
                "query_rewrite_complete",
                original_query=query,
                session_id=resolved_session_id,
                query_hash=query_hash,
                cache_hit=True,
                rewrite_model=effective_model,
            )
            return result

        # ── 请求去重：仅对真正 in-flight（尚未完成）的并发请求共享结果 ──
        # 去重键包含 session_id + query_hash，与缓存键保持一致。
        dedup_key = f"{resolved_session_id}:{query_hash}"
        if dedup_key in self._inflight:
            inflight_event = self._inflight[dedup_key]
            if not inflight_event.is_set():
                await inflight_event.wait()
                return self._inflight_results[dedup_key]
            # 前一个请求已完成 —— 清理过期状态
            del self._inflight[dedup_key]
            self._inflight_results.pop(dedup_key, None)

        event = asyncio.Event()
        self._inflight[dedup_key] = event

        try:
            result = await asyncio.wait_for(
                self._do_rewrite(
                    query,
                    history,
                    effective_model,
                    resolved_session_id,
                    query_hash,
                ),
                timeout=self._pipeline_timeout,
            )
            self._inflight_results[dedup_key] = result
            return result
        except TimeoutError:
            self._logger.warning(
                "query_rewrite_timeout",
                original_query=query,
                session_id=resolved_session_id,
                timeout_s=self._pipeline_timeout,
            )
            result = RewriteResult(
                original_query=query,
                rewritten_queries=[{"query": query, "strategy": "direct"}],
                rewrite_model=effective_model,
            )
            self._inflight_results[dedup_key] = result
            return result
        finally:
            event.set()

    # ── internal pipeline ───────────────────────────────────────────────

    async def _do_rewrite(
        self,
        query: str,
        history: list[dict] | None,
        rewrite_model: str,
        session_id: str,
        query_hash: str,
    ) -> RewriteResult:
        """执行实际的重写管线（调用方已处理 L1 缓存与请求去重）。

        管线顺序：
            精确词保护 → 上下文融合（条件触发：查询含指代词且有对话历史时触发）
            → 保护词还原 → 写入 L1 缓存 → 审计日志记录

        缓存检查由 ``rewrite()`` 在最顶层完成 —— 进入本方法时已确认未命中，
        因此直接执行完整管线。
        """
        start_time = time.monotonic()

        try:
            # Step 1: 精确词保护
            protected_query, term_map = self._protector.protect(query)  # type: ignore[union-attr]

            # Step 2: 上下文融合
            # 条件触发：查询含指代词 + 有对话历史
            strategies: list[str] = []
            rewritten = protected_query

            trigger_context_fusion = self._has_pronouns(protected_query) and bool(history)

            if trigger_context_fusion:
                rewritten = self._context_rewriter.rewrite(  # type: ignore[union-attr]
                    protected_query, history=history, model=rewrite_model
                )
                if inspect.isawaitable(rewritten):
                    rewritten = await rewritten
                strategies.append("context_fusion")

            # Step 3: 保护词还原
            final_query = self._protector.restore(  # type: ignore[union-attr]
                rewritten, term_map
            )

            # Step 4: 构建结果
            elapsed_ms = (time.monotonic() - start_time) * 1000
            strategy_label = strategies[-1] if strategies else "direct"
            result = RewriteResult(
                original_query=query,
                rewritten_queries=[{"query": final_query, "strategy": strategy_label}],
                strategies_used=strategies,
                rewrite_time_ms=elapsed_ms,
                cache_hit=False,
                rewrite_model=rewrite_model,
            )

            # Step 5: 写入 L1 缓存（会话绑定）
            self._cache_manager.store(  # type: ignore[union-attr]
                session_id, query_hash, result
            )

            # Step 6: 审计日志
            self._audit_trail.record(  # type: ignore[union-attr]
                "query_rewrite_complete",
                original_query=query,
                session_id=session_id,
                query_hash=query_hash,
                strategies_executed=strategies,
                rewrites=result.rewritten_queries,
                total_rewrite_time_ms=elapsed_ms,
                cache_hit=False,
                rewrite_model=rewrite_model,
            )

            return result

        except (ChatAPIError, RuntimeError) as exc:
            self._logger.warning(
                "query_rewrite_failed",
                original_query=query,
                session_id=session_id,
                error=str(exc),
            )
            elapsed_ms = (time.monotonic() - start_time) * 1000
            result = RewriteResult(
                original_query=query,
                rewritten_queries=[{"query": query, "strategy": "direct"}],
                rewrite_time_ms=elapsed_ms,
                cache_hit=False,
                rewrite_model=rewrite_model,
            )
            # 记录失败审计
            self._audit_trail.record(  # type: ignore[union-attr]
                "query_rewrite_failed",
                original_query=query,
                session_id=session_id,
                query_hash=query_hash,
                error=str(exc),
                total_rewrite_time_ms=elapsed_ms,
                rewrite_model=rewrite_model,
            )
            return result

    # ── helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _has_pronouns(query: str) -> bool:
        """检查查询是否包含中文指代词，用于判断是否需要上下文融合。"""
        return any(p in query for p in _PRONOUNS)
