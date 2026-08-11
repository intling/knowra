"""QueryRewriter 顶层编排器 —— 查询重写管线的集成与编排。

Phase 1 管线流程：
    L1 缓存查询 → 请求去重 → 精确词保护 → 上下文融合（条件触发）
    → 保护词还原 → 写入 L1 缓存 → 审计日志记录

Phase 2 管线流程（模块二）：
    L1 缓存查询（不满意检测跳过）→ 请求去重 → 精确词保护
    → 上下文融合（条件触发）→ L2 语义缓存查询 → 意图分类
    → 策略路由决策 → 策略串联执行（normalize → term_align → expand）
    → 保护词还原 → 写入 L1 缓存 → 审计日志记录

会话绑定缓存（模块一）：
    - 缓存 Key 绑定会话 ID，不同会话的相同问题不共享缓存
    - 精确匹配：原始 Query 字符串逐字符完全一致时命中

Phase 2 新增特性：
    - 不满意重试检测：同一会话短时间内重复提问 → 跳过 L1 缓存 + 升级策略
    - L2 语义缓存：基于查询语义向量的跨会话缓存
    - 意图分类 + 策略路由：根据查询意图和复杂度选择重写策略
    - 多策略串联：前策略输出作为后策略输入

Usage::

    rewriter = QueryRewriter(
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
    )
    result = await rewriter.rewrite("它怎么用", session_id="sess_abc", history=[...])
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
import time
from dataclasses import dataclass, field, replace
from typing import Literal

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


# ── DissatisfactionDetector ───────────────────────────────────────────────


class DissatisfactionDetector:
    """不满意重试检测器 —— 短期滑动窗口内的重复查询检测。

    维护 ``(session_id, query_hash) → last_seen_at`` 的简短记录，
    当同一会话中相同规范化查询在窗口内再次出现时判定为"不满意重试"。

    Usage::

        detector = DissatisfactionDetector(window_seconds=60.0)
        if detector.check("sess_abc", "abc123..."):
            # 不满意重试 → 跳过 L1 缓存，升级策略
            ...
        # 查询完成后记录
        detector.record("sess_abc", "abc123...")
    """

    def __init__(self, window_seconds: float = 60.0) -> None:
        self._window = window_seconds
        self._seen: dict[str, float] = {}  # (session_id, query_hash) → timestamp
        self._logger = get_logger(__name__)

    def check(self, session_id: str, query_hash: str) -> bool:
        """检查当前查询是否在窗口内已出现过。

        Args:
            session_id: 会话标识符。
            query_hash: 查询文本的哈希值。

        Returns:
            ``True`` 表示检测到不满意重试信号，应跳过 L1 缓存。
        """
        key = f"{session_id}:{query_hash}"
        last_seen = self._seen.get(key)
        if last_seen is None:
            return False

        elapsed = time.monotonic() - last_seen
        if elapsed <= self._window:
            self._logger.debug(
                "dissatisfaction_retry_detected",
                session_id=session_id,
                query_hash=query_hash,
                elapsed_s=elapsed,
            )
            return True

        return False

    def record(self, session_id: str, query_hash: str) -> None:
        """记录当前查询的时间戳，供后续检测使用。

        Args:
            session_id: 会话标识符。
            query_hash: 查询文本的哈希值。
        """
        key = f"{session_id}:{query_hash}"
        self._seen[key] = time.monotonic()
        # 定期清理过期条目：每次记录时顺便清理
        self._prune()

    def _prune(self) -> None:
        """清理超过窗口期 2 倍的过期条目，防止内存泄漏。"""
        now = time.monotonic()
        expired = [k for k, ts in self._seen.items() if now - ts > self._window * 2]
        for k in expired:
            del self._seen[k]


# ── KnowledgeClassifier ─────────────────────────────────────────────────────


class KnowledgeClassifier:
    """轻量级知识分类器 —— 判断改写结果属于通用知识还是上下文依赖。

    基于启发式规则（零 LLM 成本）对缓存结果进行分类：
    - ``"general_knowledge"``: 可跨会话复用（如 "报销流程"、"Python 语法"）
    - ``"context_dependent"``: 依赖对话历史，仅限当前会话 L1 复用
      （如 "基于刚才的代码"、"上面提到的错误"）

    Usage::

        classifier = KnowledgeClassifier()
        ktype = classifier.classify("Python 语法", rewritten_queries=[...])
        # → "general_knowledge"
    """

    # 指示上下文依赖的中文短语
    _CONTEXT_DEPENDENT_MARKERS: tuple[str, ...] = (
        "刚才",
        "之前",
        "上面",
        "上述",
        "前面",
        "前面提到",
        "上次",
        "刚刚",
        "之前说",
        "之前的",
        "基于刚才",
        "基于上面",
        "根据上面",
        "根据刚才",
        "前面说的",
        "之前提到的",
        "上面提到的",
        "刚才说的",
    )

    @classmethod
    def classify(
        cls,
        original_query: str,
        rewritten_queries: list[dict] | None = None,
    ) -> str:
        """根据查询内容分类知识类型。

        启发式规则：
        - 原始查询包含上下文依赖标记 → ``"context_dependent"``
        - 否则 → ``"general_knowledge"``

        Args:
            original_query: 用户原始查询文本。
            rewritten_queries: 改写后的查询列表（可选，供未来 LLM 判断使用）。

        Returns:
            ``"general_knowledge"`` 或 ``"context_dependent"``。
        """
        query_lower = original_query.lower().strip()
        for marker in cls._CONTEXT_DEPENDENT_MARKERS:
            if marker in query_lower:
                return "context_dependent"
        return "general_knowledge"


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
        intent: Phase 2 —— 查询意图分类结果（factual/analytical/comparative/
                procedural/exploratory/chitchat/ambiguous）。
        complexity: Phase 2 —— 查询复杂度评分（1-10 或 None）。
        cache_level: Phase 2 —— 缓存命中层级（"L1" / "L2" / None）。
        quality_scores: 集成联调 —— 改写质量 5 维评分。
        backtrack_triggered: 集成联调 —— 是否触发过回溯重试。
        backtrack_strategy: 集成联调 —— 回溯后使用的策略名称。
    """

    original_query: str
    rewritten_queries: list[dict] = field(default_factory=list)
    strategies_used: list[str] = field(default_factory=list)
    rewrite_time_ms: float = 0.0
    cache_hit: bool = False
    rewrite_model: str | None = None
    intent: str | None = None
    complexity: int | None = None
    cache_level: Literal["L1", "L2"] | None = None
    quality_scores: object | None = None  # QualityScores | None
    backtrack_triggered: bool = False
    backtrack_strategy: str | None = None
    quality_fallback: bool = False

    def __post_init__(self) -> None:
        if self.rewrite_time_ms < 0:
            raise ValueError(f"rewrite_time_ms must be >= 0, got {self.rewrite_time_ms}")


# ── QueryRewriter ──────────────────────────────────────────────────────────

# 策略名 → 重写器属性名映射
_STRATEGY_REWRITER_ATTR: dict[str, str] = {
    "normalize": "_normalize_rewriter",
    "term_align": "_term_align_rewriter",
    "expand": "_expand_rewriter",
}

# 策略名 → 启用开关属性名映射
_STRATEGY_ENABLED_ATTR: dict[str, str] = {
    "normalize": "_strategy_normalize_enabled",
    "term_align": "_strategy_term_align_enabled",
    "expand": "_strategy_expand_enabled",
}

# 策略优先级（数值越小越优先，预算紧张时先执行高优先级策略）
_STRATEGY_PRIORITY: dict[str, int] = {
    "normalize": 0,
    "term_align": 1,
    "expand": 2,
}


class QueryRewriter:
    """查询重写顶层编排器。

    组合 ExactTermProtector、ContextRewriter、CacheManager、StrategyRouter、
    NormalizeRewriter、TermAlignRewriter、ExpandRewriter、DissatisfactionDetector、
    AuditTrail，通过 ``rewrite(query, session_id, history)`` 单一入口执行
    完整重写管线。

    管线顺序（Phase 2）：
        不满意重试检测 → L1 缓存查询（会话绑定）→ 请求去重 → 精确词保护
        → 上下文融合（条件触发）→ L2 语义缓存查询 → 意图分类 + 策略路由
        → 策略串联执行（normalize → term_align → expand）→ 保护词还原
        → 写入 L1 缓存 → 审计日志记录

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
        pipeline_timeout: float = 20.0,
        strategy_timeout: float = 10.0,
        # ── Phase 2 新增依赖（全部可选，向后兼容 Phase 1）──
        strategy_router: object | None = None,
        normalize_rewriter: object | None = None,
        term_align_rewriter: object | None = None,
        expand_rewriter: object | None = None,
        dissatisfaction_detector: object | None = None,
        dissatisfaction_window_seconds: float = 60.0,
        strategy_normalize_enabled: bool = True,
        strategy_expand_enabled: bool = True,
        strategy_term_align_enabled: bool = True,
        l2_similarity_threshold: float = 0.95,
        knowledge_classifier: object | None = None,
        context_verifier: object | None = None,
        # ── 集成联调 新增依赖 ──
        postprocessor: object | None = None,
        max_backtrack_attempts: int = 1,
        # ── 熔断器 ──
        circuit_breaker: object | None = None,
        # ── 差异化 TTL 配置（从 Settings 注入，替换硬编码）──
        l1_general_ttl: float = 1800.0,
        l1_context_dependent_ttl: float = 300.0,
        l2_general_ttl: float = 3600.0,
        l2_context_dependent_ttl: float = 600.0,
    ) -> None:
        self._protector = exact_term_protector
        self._context_rewriter = context_rewriter
        self._cache_manager = cache_manager
        self._chat_adapter = chat_adapter
        self._audit_trail = audit_trail
        self._enabled = enabled
        self._pipeline_timeout = pipeline_timeout
        self._strategy_timeout = strategy_timeout

        # Phase 2 dependencies
        self._strategy_router = strategy_router
        self._normalize_rewriter = normalize_rewriter
        self._term_align_rewriter = term_align_rewriter
        self._expand_rewriter = expand_rewriter
        self._dissatisfaction_detector = dissatisfaction_detector
        self._dissatisfaction_window_seconds = dissatisfaction_window_seconds
        self._strategy_normalize_enabled = strategy_normalize_enabled
        self._strategy_expand_enabled = strategy_expand_enabled
        self._strategy_term_align_enabled = strategy_term_align_enabled
        self._l2_similarity_threshold = l2_similarity_threshold
        self._knowledge_classifier = knowledge_classifier
        self._context_verifier = context_verifier

        # 集成联调 dependencies
        self._postprocessor = postprocessor
        self._max_backtrack_attempts = max_backtrack_attempts

        # 熔断器
        self._circuit_breaker = circuit_breaker

        # 差异化 TTL 配置
        self._l1_general_ttl = l1_general_ttl
        self._l1_context_dependent_ttl = l1_context_dependent_ttl
        self._l2_general_ttl = l2_general_ttl
        self._l2_context_dependent_ttl = l2_context_dependent_ttl

        self._logger = get_logger(__name__)

        # 请求去重：in-flight 查询追踪
        self._inflight: dict[str, asyncio.Event] = {}
        self._inflight_results: dict[str, RewriteResult] = {}

    # ── 指纹管理 ─────────────────────────────────────────────────────────

    def update_fingerprint(self, fingerprint: str | None) -> None:
        """更新知识库指纹到内部 CacheManager（由搜索管线在每次请求前调用）。

        传入 ``None`` 表示禁用指纹校验。
        """
        if self._cache_manager is not None:
            self._cache_manager.update_fingerprint(fingerprint)  # type: ignore[union-attr]

    # ── helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_query(query: str) -> str:
        """规范化查询文本，用于缓存键比较。

        规则（遵循 design.md Decision 5）：
            - 去除首尾空白
            - 连续空白字符折叠为单个空格
            - Unicode NFC 标准化
            - 不做大小写折叠（中文无意义，英文术语大小写可能承载语义差异如 "US" vs "us"）
        """
        import unicodedata

        # 1. 去除首尾空白 + 2. 折叠连续空白
        collapsed = " ".join(query.strip().split())
        # 3. Unicode NFC 标准化
        return unicodedata.normalize("NFC", collapsed)

    @staticmethod
    def _hash_query(query: str) -> str:
        """对查询文本计算 SHA-256 哈希前缀。

        先对查询文本进行规范化处理（trim + 空白折叠 + NFC 标准化），
        再计算 SHA-256 哈希。规范化确保相同语义意图但格式差异
        （如多余空格）的查询命中相同缓存条目。

        返回 16 字符十六进制哈希，用于缓存键。
        """
        normalized = QueryRewriter._normalize_query(query)
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

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

    def _is_strategy_enabled(self, strategy_name: str) -> bool:
        """检查指定策略是否被启用。

        Args:
            strategy_name: 策略名称（"normalize" / "term_align" / "expand"）。

        Returns:
            ``True`` 表示该策略开关已启用。
        """
        attr = _STRATEGY_ENABLED_ATTR.get(strategy_name)
        if attr is None:
            return False
        return getattr(self, attr, False)

    def _get_strategy_rewriter(self, strategy_name: str) -> object | None:
        """获取指定策略对应的重写器实例。

        Args:
            strategy_name: 策略名称（"normalize" / "term_align" / "expand"）。

        Returns:
            对应的重写器实例，不存在时返回 ``None``。
        """
        attr = _STRATEGY_REWRITER_ATTR.get(strategy_name)
        if attr is None:
            return None
        return getattr(self, attr, None)

    # 当前支持的策略升级链：normalize → expand, term_align → expand
    _BACKTRACK_UPGRADE_CHAIN: dict[str, str] = {
        "normalize": "expand",
        "term_align": "expand",
    }

    def _resolve_backtrack_strategy(self, attempted_strategies: list[str]) -> str | None:
        """解析回溯升级策略。

        当前升级链：``normalize`` → ``expand``。
        更多升级链可通过配置扩展。

        Args:
            attempted_strategies: 已尝试的策略名称列表。

        Returns:
            升级后的策略名称，无可用升级时返回 ``None``。
        """
        for strategy_item in attempted_strategies:
            upgrade = self._BACKTRACK_UPGRADE_CHAIN.get(strategy_item)
            if upgrade is not None and upgrade not in attempted_strategies:
                return upgrade
        return None

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

        # ── 熔断器检查：已断开 → 跳过重写，直接返回原始查询 ──
        if self._circuit_breaker is not None and not self._circuit_breaker.before_call():
            self._logger.debug(
                "circuit_breaker_open",
                original_query=query,
                session_id=resolved_session_id,
            )
            return RewriteResult(
                original_query=query,
                rewritten_queries=[{"query": query, "strategy": "direct"}],
                rewrite_model=effective_model,
            )

        # ── 查询哈希（直接对原始查询文本哈希，用于精确匹配缓存）──
        query_hash = self._hash_query(query)

        # ── 不满意重试检测（Phase 2）──
        # 在 L1 缓存之前检查 —— 不满意时跳过缓存以触发升级策略
        is_dissatisfaction = False
        if self._dissatisfaction_detector is not None:
            is_dissatisfaction = self._dissatisfaction_detector.check(
                resolved_session_id, query_hash
            )
            if is_dissatisfaction:
                self._audit_trail.record(  # type: ignore[union-attr]
                    "dissatisfaction_retry",
                    original_query=query,
                    session_id=resolved_session_id,
                    query_hash=query_hash,
                    rewrite_model=effective_model,
                )

        # ── L1 缓存：会话绑定查找（不满意重试时跳过）──
        if not is_dissatisfaction:
            cached = self._cache_manager.lookup(  # type: ignore[union-attr]
                resolved_session_id, query_hash
            )
            if cached is not None:
                result = replace(cached, cache_hit=True, cache_level="L1")
                self._audit_trail.record(  # type: ignore[union-attr]
                    "query_rewrite_complete",
                    original_query=query,
                    session_id=resolved_session_id,
                    query_hash=query_hash,
                    cache_hit=True,
                    cache_level="L1",
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
                result = self._inflight_results[dedup_key]
                # 不满意重试时仍记录当前查询
                if self._dissatisfaction_detector is not None:
                    self._dissatisfaction_detector.record(resolved_session_id, query_hash)
                return result
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
                    is_dissatisfaction=is_dissatisfaction,
                ),
                timeout=self._pipeline_timeout,
            )
            self._inflight_results[dedup_key] = result

            # ── 熔断器：成功通知 ──
            if self._circuit_breaker is not None:
                self._circuit_breaker.on_success()

            # ── 记录当前查询用于未来不满意检测（Phase 2）──
            if self._dissatisfaction_detector is not None:
                self._dissatisfaction_detector.record(resolved_session_id, query_hash)

            return result
        except TimeoutError:
            # ── 熔断器：失败通知 ──
            if self._circuit_breaker is not None:
                self._circuit_breaker.on_failure()

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
            # 超时时也记录（供未来检测）
            if self._dissatisfaction_detector is not None:
                self._dissatisfaction_detector.record(resolved_session_id, query_hash)
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
        is_dissatisfaction: bool = False,
    ) -> RewriteResult:
        """执行实际的重写管线（调用方已处理 L1 缓存与请求去重）。

        管线顺序（Phase 2）：
            精确词保护 → 上下文融合（条件触发：查询含指代词且有对话历史时触发）
            → L2 语义缓存查询 → 意图分类 + 策略路由 → 策略串联执行
            → 保护词还原 → 写入 L1 缓存 → 审计日志记录

        缓存检查由 ``rewrite()`` 在最顶层完成 —— 进入本方法时已确认 L1 未命中，
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
                rewritten = await self._run_sync_in_thread(
                    self._context_rewriter.rewrite,  # type: ignore[union-attr]
                    protected_query,
                    history=history,
                    model=rewrite_model,
                )
                strategies.append("context_fusion")

            # Step 2.5: L2 语义缓存查询（Phase 2）
            l2_lookup = getattr(self._cache_manager, "lookup_l2", None)  # type: ignore[union-attr]
            if l2_lookup is not None:
                try:
                    l2_cached = l2_lookup(rewritten)
                    if l2_cached is not None:
                        result = None
                        if isinstance(l2_cached, RewriteResult):
                            # 直接返回 RewriteResult（向后兼容，无元数据）
                            result = replace(
                                l2_cached,
                                cache_hit=True,
                                cache_level="L2",
                            )
                        elif isinstance(l2_cached, dict) and "result" in l2_cached:
                            # 结构化 L2 返回（含相似度、知识类型等元数据）
                            similarity = l2_cached.get("similarity", 1.0)
                            knowledge_type = l2_cached.get("knowledge_type", "general_knowledge")
                            source_session = l2_cached.get("source_session_id")

                            # ── 相似度阈值检查 ──
                            if similarity < self._l2_similarity_threshold:
                                # 相似度不足，跳过 L2 缓存，继续正常管线
                                self._audit_trail.record(  # type: ignore[union-attr]
                                    "l2_similarity_rejected",
                                    original_query=query,
                                    session_id=session_id,
                                    similarity=similarity,
                                    threshold=self._l2_similarity_threshold,
                                )
                                result = None
                            # ── 知识类型检查：context_dependent 跨会话拦截 ──
                            elif (
                                knowledge_type == "context_dependent"
                                and source_session is not None
                                and source_session != session_id
                            ):
                                self._audit_trail.record(  # type: ignore[union-attr]
                                    "l2_context_rejected",
                                    original_query=query,
                                    session_id=session_id,
                                    source_session_id=source_session,
                                    knowledge_type=knowledge_type,
                                )
                                result = None
                            else:
                                inner = l2_cached["result"]
                                result = replace(
                                    inner,
                                    cache_hit=True,
                                    cache_level="L2",
                                )
                        # else: 无法识别 L2 返回格式 → result = None（降级到正常管线）

                        if result is not None:
                            # ── 上下文相关性校验（Phase 2 - 7.2.4c）──
                            # L2 命中后调用轻量 LLM 判断缓存答案是否依赖当前上下文。
                            # context_dependent 跨会话已在上面拦截；仅有 general_knowledge
                            # 和同会话 context_dependent 到达此处。
                            if self._context_verifier is not None:
                                try:
                                    verification = await self._run_sync_in_thread(
                                        self._context_verifier.verify,
                                        result.original_query,
                                        history=history,
                                    )
                                    if verification.get("context_dependent", False):
                                        # 校验不通过 → 回退到正常重写管线
                                        self._audit_trail.record(  # type: ignore[union-attr]
                                            "l2_context_rejected",
                                            original_query=query,
                                            session_id=session_id,
                                            reason=verification.get("reasoning", ""),
                                            cache_hit=False,
                                        )
                                        result = None
                                except Exception:
                                    # 校验 LLM 调用失败 → 保守接受缓存结果，不阻断管线
                                    pass

                            if result is not None:
                                self._audit_trail.record(  # type: ignore[union-attr]
                                    "query_rewrite_complete",
                                    original_query=query,
                                    session_id=session_id,
                                    query_hash=query_hash,
                                    cache_hit=True,
                                    cache_level="L2",
                                    strategies_executed=result.strategies_used,
                                    rewrites=result.rewritten_queries,
                                    total_rewrite_time_ms=(time.monotonic() - start_time) * 1000,
                                    rewrite_model=rewrite_model,
                                )
                                return result
                except Exception:
                    # L2 查询失败非关键，继续正常管线
                    pass

            # Step 3: 意图分类 + 策略路由（Phase 2）
            intent: str | None = None
            complexity: int | None = None
            routed_strategies: list[str] = []

            if self._strategy_router is not None:
                try:
                    route_result = await self._run_sync_in_thread(
                        self._strategy_router.route,
                        rewritten,
                    )
                    intent = route_result.get("intent")
                    complexity = route_result.get("complexity")
                    routed_strategies = route_result.get("strategies", [])
                except Exception:
                    # 策略路由失败时降级：不执行任何策略
                    routed_strategies = []

            # Step 4: 策略执行（Phase 2）
            # - 策略优先级排序：预算不足时按 normalize > term_align > expand 排序
            # - normalize 和 term_align 无依赖关系，预算充足时可并行执行
            # - 每个策略通过 asyncio.wait_for 施加硬超时，确保单策略执行可被中断
            strategy_rewrites: list[dict] = []
            current_query = rewritten
            rewrite_input = current_query  # 保存策略输入，供回溯使用
            protected_terms_list = list(term_map.values()) if term_map else None

            # ── 管线预算感知的超时分配 ──
            # 统计实际可执行的策略数量（排除开关关闭或 rewriter 缺失的）
            executable_strategies = [
                s
                for s in routed_strategies
                if self._is_strategy_enabled(s) and self._get_strategy_rewriter(s) is not None
            ]

            if executable_strategies:
                # ── 计算管线剩余预算 ──
                elapsed = time.monotonic() - start_time
                remaining_budget = max(0, self._pipeline_timeout - elapsed)

                # ── 检测可并行执行的策略对（normalize + term_align 无依赖）──
                has_normalize = "normalize" in executable_strategies
                has_term_align = "term_align" in executable_strategies
                parallel_norm_term = (
                    has_normalize
                    and has_term_align
                    and remaining_budget >= 16.0  # 两个策略各需最低 8s
                )

                if parallel_norm_term:
                    # 并行路径：normalize + term_align 并行，其余按优先级顺序执行
                    sequential_strategies = [
                        s for s in executable_strategies if s not in ("normalize", "term_align")
                    ]
                else:
                    # 顺序路径：所有策略按优先级排序执行
                    sequential_strategies = sorted(
                        executable_strategies,
                        key=lambda s: _STRATEGY_PRIORITY.get(s, 99),
                    )

                # ══════════════════════════════════════════════════════════════
                # Step 4a: 并行执行 normalize + term_align（无依赖，预算充足时）
                #
                # 注意：并行块必须在串行块之前执行！
                # normalize 的高优先级输出会作为 current_query 传递给后续策略
                # （如 expand），确保 expand 收到最佳输入。
                # ══════════════════════════════════════════════════════════════

                if parallel_norm_term:
                    elapsed = time.monotonic() - start_time
                    parallel_budget = max(0, self._pipeline_timeout - elapsed)

                    if parallel_budget >= 8.0:
                        # 每个策略分配剩余预算的一半，但不低于 8s、不超过 strategy_timeout
                        parallel_timeout = max(
                            8.0,
                            min(self._strategy_timeout, parallel_budget / 2),
                        )

                        norm_rewriter = self._get_strategy_rewriter("normalize")
                        term_rewriter = self._get_strategy_rewriter("term_align")

                        async def _exec_normalize():
                            try:
                                return await asyncio.wait_for(
                                    self._run_sync_in_thread(
                                        norm_rewriter.rewrite,
                                        current_query,
                                        protected_terms=protected_terms_list,
                                        request_timeout=parallel_timeout,
                                        max_retries=self._chat_adapter.config.max_retries,
                                    ),
                                    timeout=parallel_timeout,
                                )
                            except (asyncio.TimeoutError, Exception):
                                return None

                        async def _exec_term_align():
                            try:
                                return await asyncio.wait_for(
                                    self._run_sync_in_thread(
                                        term_rewriter.rewrite,
                                        current_query,
                                        protected_terms=protected_terms_list,
                                        request_timeout=parallel_timeout,
                                        max_retries=self._chat_adapter.config.max_retries,
                                    ),
                                    timeout=parallel_timeout,
                                )
                            except (asyncio.TimeoutError, Exception):
                                return None

                        # 并行执行，各自处理异常，互不影响
                        norm_result, term_result = await asyncio.gather(
                            _exec_normalize(),
                            _exec_term_align(),
                        )

                        # ── 合并并行结果：normalize 优先（更高优先级）──
                        # normalize 结果作为后续策略的基础输入
                        if norm_result is not None:
                            norm_query = norm_result.get("query", current_query)
                            strategy_rewrites.append(
                                {
                                    "query": norm_query,
                                    "strategy": "normalize",
                                    "duration_ms": norm_result.get("duration_ms"),
                                    "tokens": norm_result.get("tokens"),
                                }
                            )
                            strategies.append("normalize")
                            current_query = norm_query

                        if term_result is not None:
                            term_query = term_result.get("query", current_query)
                            strategy_rewrites.append(
                                {
                                    "query": term_query,
                                    "strategy": "term_align",
                                    "duration_ms": term_result.get("duration_ms"),
                                    "tokens": term_result.get("tokens"),
                                }
                            )
                            strategies.append("term_align")

                # ══════════════════════════════════════════════════════════════
                # Step 4b: 顺序执行剩余策略（按优先级排序）
                # ══════════════════════════════════════════════════════════════

                for i, strategy_name in enumerate(sequential_strategies):
                    if not self._is_strategy_enabled(strategy_name):
                        continue

                    rewriter = self._get_strategy_rewriter(strategy_name)
                    if rewriter is None:
                        continue

                    # ── 计算该策略的剩余超时 ──
                    remaining_count = len(sequential_strategies) - i
                    elapsed = time.monotonic() - start_time
                    remaining_budget = max(0, self._pipeline_timeout - elapsed)
                    per_strategy_timeout = max(
                        8.0,
                        min(
                            self._strategy_timeout,
                            remaining_budget / max(remaining_count, 1),
                        ),
                    )

                    if remaining_budget < 8.0:
                        self._logger.warning(
                            "pipeline_budget_exhausted",
                            original_query=query,
                            session_id=session_id,
                            elapsed_s=elapsed,
                            remaining_budget_s=remaining_budget,
                            skipped_strategies=sequential_strategies[i:],
                        )
                        break

                    try:
                        # ── asyncio.wait_for 硬超时：确保单策略可被中断 ──
                        strategy_result = await asyncio.wait_for(
                            self._run_sync_in_thread(
                                rewriter.rewrite,
                                current_query,
                                protected_terms=protected_terms_list,
                                request_timeout=per_strategy_timeout,
                                max_retries=self._chat_adapter.config.max_retries,
                            ),
                            timeout=per_strategy_timeout,
                        )

                        new_query = strategy_result.get("query", current_query)
                        strategy_rewrites.append(
                            {
                                "query": new_query,
                                "strategy": strategy_name,
                                "duration_ms": strategy_result.get("duration_ms"),
                                "tokens": strategy_result.get("tokens"),
                            }
                        )
                        current_query = new_query
                        strategies.append(strategy_name)
                    except asyncio.TimeoutError:
                        self._logger.warning(
                            "strategy_hard_timeout",
                            strategy=strategy_name,
                            original_query=query,
                            session_id=session_id,
                            timeout_s=per_strategy_timeout,
                        )
                    except Exception:
                        # 单个策略失败不阻断管线，继续使用当前查询执行后续策略
                        pass

            # ── 集成联调: Postprocessor 质量评估与回溯 ──
            # 每条策略执行后 → Postprocessor.evaluate() → 确定性预检查
            # → LLM 质量评估 → 质量合格则保留，不合格则回溯（最多 1 次）
            # → 二次失败丢弃回退原始查询
            quality_scores: object | None = None
            backtrack_triggered = False
            backtrack_strategy: str | None = None
            quality_fallback = False

            if self._postprocessor is not None and strategy_rewrites:
                # ── 对最终改写结果进行质量评估 ──
                final_rewrite = strategy_rewrites[-1]["query"]

                try:
                    eval_result = await self._run_sync_in_thread(
                        self._postprocessor.evaluate,
                        query,  # original_query
                        final_rewrite,  # rewritten_query
                        intent,  # ← 传入意图类型，用于分层阈值
                    )
                except Exception:
                    # Postprocessor 调用异常 → 降级，保守接受改写
                    self._logger.warning(
                        "postprocessor_evaluate_exception",
                        original_query=query,
                        session_id=session_id,
                    )
                    eval_result = {
                        "quality_scores": None,
                        "passed": True,  # 保守接受
                        "pre_check_failed": False,
                        "pre_check_issues": [],
                    }

                passed = eval_result.get("passed", True)
                quality_scores = eval_result.get("quality_scores")
                pre_check_failed = eval_result.get("pre_check_failed", False)

                # ── 单策略 normalize 降级快速路径 ──
                # normalize 仅是清理/补全，不改变语义结构，预检失败时不丢弃，
                # 而是标记 quality_fallback 接受改写。
                is_normalize_only = (
                    len(routed_strategies) == 1
                    and routed_strategies[0] == "normalize"
                )
                if not passed and is_normalize_only and pre_check_failed:
                    passed = True
                    pre_check_failed = False
                    quality_fallback = True
                    self._logger.info(
                        "quality_fallback_normalize_only",
                        original_query=query,
                        session_id=session_id,
                        rewritten_query=final_rewrite,
                    )
                    self._audit_trail.record(  # type: ignore[union-attr]
                        "quality_fallback_normalize_only",
                        original_query=query,
                        rewritten_query=final_rewrite,
                    )

                if not passed:
                    # ── 回溯逻辑：升级策略重新改写（最多 max_backtrack_attempts 次）──
                    upgrade_strategy_name = self._resolve_backtrack_strategy(routed_strategies)

                    if upgrade_strategy_name and self._max_backtrack_attempts >= 1:
                        # 执行升级策略
                        upgrade_rewriter = self._get_strategy_rewriter(upgrade_strategy_name)
                        if upgrade_rewriter is not None and self._is_strategy_enabled(
                            upgrade_strategy_name
                        ):
                            try:
                                upgrade_result = await self._run_sync_in_thread(
                                    upgrade_rewriter.rewrite,
                                    rewrite_input,
                                    protected_terms=protected_terms_list,
                                    request_timeout=getattr(self, "_strategy_timeout", 30.0),
                                    max_retries=self._chat_adapter.config.max_retries,  # type: ignore[union-attr]
                                )

                                backtrack_query = upgrade_result.get("query", current_query)
                                backtrack_triggered = True
                                backtrack_strategy = upgrade_strategy_name

                                # 追加回溯改写记录
                                strategy_rewrites.append(
                                    {
                                        "query": backtrack_query,
                                        "strategy": upgrade_strategy_name,
                                        "duration_ms": upgrade_result.get("duration_ms"),
                                        "tokens": upgrade_result.get("tokens"),
                                    }
                                )
                                strategies.append(upgrade_strategy_name)
                                current_query = backtrack_query

                                # ── 对回溯结果再次评估 ──
                                try:
                                    retry_eval = await self._run_sync_in_thread(
                                        self._postprocessor.evaluate,
                                        query,
                                        backtrack_query,
                                        intent,  # ← 传入意图类型，用于分层阈值
                                    )
                                    retry_passed = retry_eval.get("passed", False)
                                    quality_scores = retry_eval.get("quality_scores")

                                    if retry_passed:
                                        # 二次评估通过 → 使用升级后的改写
                                        self._audit_trail.record(  # type: ignore[union-attr]
                                            "quality_backtrack_success",
                                            original_query=query,
                                            session_id=session_id,
                                            initial_rewrite=final_rewrite,
                                            backtrack_strategy=upgrade_strategy_name,
                                            backtrack_rewrite=backtrack_query,
                                        )
                                    else:
                                        # 二次失败 → 丢弃改写，使用原始查询
                                        self._logger.info(
                                            "quality_backtrack_failed_discarding",
                                            original_query=query,
                                            session_id=session_id,
                                            initial_rewrite=final_rewrite,
                                            backtrack_rewrite=backtrack_query,
                                        )
                                        current_query = query  # 回退到原始查询
                                        strategy_rewrites = [{"query": query, "strategy": "direct"}]
                                        strategies = []
                                except Exception:
                                    # 二次评估异常 → 降级，保守接受回溯结果
                                    self._logger.warning(
                                        "quality_backtrack_evaluate_exception",
                                        original_query=query,
                                        session_id=session_id,
                                    )
                            except Exception:
                                # 升级策略执行失败 → 丢弃改写，使用原始查询
                                self._logger.warning(
                                    "quality_backtrack_strategy_failed",
                                    original_query=query,
                                    session_id=session_id,
                                    upgrade_strategy=upgrade_strategy_name,
                                )
                                current_query = query
                                strategy_rewrites = [{"query": query, "strategy": "direct"}]
                                strategies = []
                                backtrack_triggered = True
                                backtrack_strategy = upgrade_strategy_name
                        else:
                            # 升级策略不可用 → 直接丢弃
                            self._logger.info(
                                "quality_backtrack_no_upgrade_strategy",
                                original_query=query,
                                session_id=session_id,
                                attempted_upgrade=upgrade_strategy_name,
                            )
                            current_query = query
                            strategy_rewrites = [{"query": query, "strategy": "direct"}]
                            strategies = []
                            backtrack_triggered = True
                    else:
                        # 无可用升级策略或 max_backtrack_attempts == 0
                        # → 直接丢弃改写，使用原始查询
                        current_query = query
                        strategy_rewrites = [{"query": query, "strategy": "direct"}]
                        strategies = []
                        backtrack_triggered = pre_check_failed or upgrade_strategy_name is not None

            # Step 5: 保护词还原
            final_query = self._protector.restore(  # type: ignore[union-attr]
                current_query, term_map
            )

            # Update the last strategy rewrite's query to the restored version
            if strategy_rewrites:
                strategy_rewrites[-1]["query"] = final_query
            elif strategies:
                # Context fusion was the only strategy, no Phase 2 strategies executed
                strategy_rewrites.append({"query": final_query, "strategy": strategies[-1]})
            else:
                # No strategies at all → direct
                strategy_rewrites.append({"query": final_query, "strategy": "direct"})

            # Step 6: 构建结果
            elapsed_ms = (time.monotonic() - start_time) * 1000
            result = RewriteResult(
                original_query=query,
                rewritten_queries=strategy_rewrites,
                strategies_used=strategies,
                rewrite_time_ms=elapsed_ms,
                cache_hit=False,
                rewrite_model=rewrite_model,
                intent=intent,
                complexity=complexity,
                cache_level=None,
                quality_scores=quality_scores,
                backtrack_triggered=backtrack_triggered,
                backtrack_strategy=backtrack_strategy,
                quality_fallback=quality_fallback,
            )

            # Step 7: 计算知识分类（L1 和 L2 缓存共用）
            knowledge_type = "general_knowledge"
            try:
                classifier = self._knowledge_classifier or KnowledgeClassifier
                knowledge_type = classifier.classify(
                    query, rewritten_queries=result.rewritten_queries
                )
            except Exception:
                pass

            # Step 7a: 写入 L1 缓存（会话绑定，带差异化 TTL）
            l1_ttl = (
                self._l1_context_dependent_ttl
                if knowledge_type == "context_dependent"
                else self._l1_general_ttl
            )
            self._cache_manager.store(  # type: ignore[union-attr]
                session_id, query_hash, result, ttl_override=l1_ttl
            )

            # Step 7b: 写入 L2 语义缓存（跨会话，含知识分类标记）
            # 设计决策：上下文依赖答案仅写 L1，不进入 L2 跨会话缓存。
            # 理由：依赖对话历史的答案（如"基于刚才的代码"）无法安全地跨会话复用，
            # 写入 L2 纯属浪费空间，且已被 L2 lookup 的跨会话拦截逻辑保护。
            store_l2 = getattr(self._cache_manager, "store_l2", None)  # type: ignore[union-attr]
            if store_l2 is not None and knowledge_type != "context_dependent":
                with contextlib.suppress(Exception):
                    store_l2(
                        final_query,
                        result,
                        knowledge_type=knowledge_type,
                        session_id=session_id,
                        ttl_override=self._l2_general_ttl,
                    )

            # Step 8: 审计日志
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
                intent=intent,
                complexity=complexity,
            )

            return result

        except (ChatAPIError, RuntimeError) as exc:
            # ── 熔断器：失败通知 ──
            if self._circuit_breaker is not None:
                self._circuit_breaker.on_failure()

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
    async def _run_sync_in_thread(func, *args, **kwargs):
        """在线程中运行可能阻塞的函数，避免阻塞事件循环。

        若 *func* 是协程函数则直接 await；否则通过 ``asyncio.to_thread``
        在独立线程中执行。对于 MagicMock 配置了 async side_effect 的特殊情况，
        在线程中执行后返回的协程会再次被 await。

        这使得 ``asyncio.wait_for(timeout=…)`` 能够真正取消超时的同步调用 ——
        当超时触发时，事件循环可以取消在线程中运行的任务。
        """
        if inspect.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        result = await asyncio.to_thread(func, *args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result

    @staticmethod
    def _has_pronouns(query: str) -> bool:
        """检查查询是否包含中文指代词，用于判断是否需要上下文融合。"""
        return any(p in query for p in _PRONOUNS)
