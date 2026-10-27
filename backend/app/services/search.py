"""Semantic search orchestration: vectorize → retrieve → generate → respond.

The ``SearchService`` is the core of the RAG pipeline.  It receives a natural-language
query, vectorises it with ``EmbeddingAdapter``, retrieves the top-K most similar chunks
via pgvector cosine distance, assembles a prompt, calls the LLM, and returns a fully
populated ``SearchResponse``.

L1 搜索响应缓存（会话绑定精确匹配）：
    当 ``response_cache`` 参数非 None 时，SearchService 会在管线开始前检查缓存，
    命中时直接返回缓存的 SearchResponse（跳过向量搜索和 LLM 生成）。
    缓存 Key = session_id + query_hash + top_k + history_digest，
    确保相同会话 + 相同查询 + 相同 top_k + 相同对话历史 才能命中。
    不可信身份（无显式 session_id 且无 history）跳过缓存写入，防止私有响应跨用户泄漏。
"""

import asyncio
import dataclasses
import hashlib
import inspect
import threading
import time
from collections.abc import Awaitable, Callable
from uuid import UUID

from anyio import CancelScope
from sqlmodel import Session, func, select

from app.core.logging import get_logger
from app.models.document_chunking import DocumentChunk
from app.models.document_embedding import DocumentEmbedding
from app.models.document_parsing import ParsedDocument
from app.models.uploaded_file import UploadedFile
from app.schemas.search import (
    AnswerTokens,
    QualityScores,
    RewriteInfo,
    RewrittenQuery,
    SearchResponse,
    SearchResult,
)
from app.services.answer_policy import (
    POLICY_VERSION,
    RAG_PROMPT,
    clarification,
    route_answer,
    system_prompt,
)
from app.services.chat_adapter import ChatAdapter, ChatAPIError
from app.services.chat_config import ChatConfig
from app.services.circuit_breaker import CircuitBreaker
from app.services.embedding_adapter import EmbeddingAdapter, EmbeddingAPIError
from app.services.rerank_adapter import RerankAdapter, RerankError
from app.services.summary_context import build_summary_context, summary_revision, validate_scope

# ── helpers ──────────────────────────────────────────────────────────────────


def _run_async(coro):
    """Safely await a coroutine in both sync and async contexts.

    Uses ``asyncio.run()`` when no event loop is active.  When called from inside
    a running event loop (e.g. Starlette's TestClient with anyio), the coroutine
    is dispatched to a fresh event loop on a background thread.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — asyncio.run() is safe.
        return asyncio.run(coro)

    # An event loop is already running.  Create a new one on a dedicated thread
    # to avoid "cannot be called from a running event loop" errors.
    result_container: dict[str, object] = {}
    error_container: dict[str, Exception] = {}

    def _target() -> None:
        try:
            result_container["value"] = asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001
            error_container["value"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join()

    if "value" in error_container:
        raise error_container["value"]
    return result_container["value"]


# ── prompt 模板 ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = RAG_PROMPT

USER_PROMPT_TEMPLATE = """以下是从知识库中检索到的相关文档内容：

{context}

请根据以上文档内容回答用户的问题。如果文档中有可以直接引用的部分，请使用引用格式。

用户问题：{query}"""

# ── 降级提示 ────────────────────────────────────────────────────────────

_CHAT_DISABLED_ANSWER = "AI 回答生成功能未启用，请联系管理员配置对话模型。"
_CHAT_FAILED_ANSWER = "AI 回答生成失败，请稍后重试。"
_CHAT_DISABLED_ERROR = "Chat generation is disabled"

# 每轮最多两次续写；整轮总时限由 ChatConfig.generation_timeout 控制。
_MAX_ANSWER_CONTINUATIONS = 2
_CONTINUE_PROMPT = (
    "上次回答达到输出长度上限。请继续完成用户原始问题，直接从已有正文末尾接续，"
    "不要重复标题、开场或已解释内容，保持原有 Markdown 和真实来源引用。"
    "优先解释尚未完成的概念并完整收尾。"
)

# 防御性截断：单条历史消息的最大字符数，防止超长历史撑爆 prompt
_HISTORY_MESSAGE_MAX_CHARS = 2000


class SearchService:
    """编排完整的 RAG 管线：查询向量化 → pgvector 检索 → LLM 生成 → 组装响应。

    构造函数通过 DI 接收 ``session``、``embedding_adapter``、``chat_adapter``、
    ``chat_config``，便于测试时替换为 fake/mock 对象。
    """

    def __init__(
        self,
        *,
        session: Session,
        owner_user_id: UUID,
        kb_fingerprint: str | None = None,
        embedding_adapter: EmbeddingAdapter,
        chat_adapter: ChatAdapter,
        chat_config: ChatConfig,
        similarity_threshold: float = 0.5,
        min_score_threshold: float = 0.45,
        query_rewriter: object | None = None,
        response_cache: object | None = None,
        audit_trail: object | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        rerank_adapter: RerankAdapter | None = None,
    ) -> None:
        self._session = session
        self._owner_user_id = owner_user_id
        self._cache_scope = f"u:{owner_user_id}:{kb_fingerprint}:{POLICY_VERSION}"
        self._document_ids: list[UUID] | None = None
        self._embedding_adapter = embedding_adapter
        self._chat_adapter = chat_adapter
        self._chat_config = chat_config
        self._similarity_threshold = similarity_threshold
        self._min_score_threshold = min_score_threshold
        self._query_rewriter = query_rewriter
        self._response_cache = response_cache
        self._audit_trail = audit_trail
        self._circuit_breaker = circuit_breaker
        self._rerank_adapter = rerank_adapter
        self._logger = get_logger(__name__)

    # ── public API ──────────────────────────────────────────────────

    @staticmethod
    def _compute_history_digest(history: list[dict] | None) -> str:
        """对 history 做确定性规范化后 SHA-256，返回 hex digest。

        空 history 或无 user/assistant 消息时返回空字符串，
        此时缓存键中不包含 history 维度（向后兼容无 history 场景）。
        """
        if not history:
            return ""
        normalized = [
            f"{msg.get('role', '')}:{msg.get('content', '')}"
            for msg in history
            if msg.get("role") in ("user", "assistant")
        ]
        if not normalized:
            return ""
        return hashlib.sha256("|".join(normalized).encode()).hexdigest()[:16]

    @staticmethod
    def _make_search_cache_key(
        session_id: str, query: str, top_k: int, history_digest: str = ""
    ) -> str:
        """生成搜索响应缓存的复合键。

        缓存键 = SHA-256(session_id + ":" + query + ":" + str(top_k)
                 + (":" + history_digest 若非空)) 的前 16 字符。

        四方组合确保：相同会话 + 完全相同查询文本 + 相同 top_k
        + 相同对话历史 才能命中。
        """
        raw = f"{session_id}:{query}:{top_k}"
        if history_digest:
            raw += f":{history_digest}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _resolve_session_id(session_id: str | None, history: list[dict] | None) -> str | None:
        """解析会话标识符：显式传入优先，否则从 history 哈希派生。

        当无法确定可信身份时（无显式 session_id 且无 history）返回 ``None``，
        调用方应据此跳过私有响应缓存写入。

        复用 ``_compute_history_digest`` 的规范化逻辑，避免重复实现。
        """
        if session_id:
            return session_id
        digest = SearchService._compute_history_digest(history)
        return digest if digest else None

    def search(
        self,
        query: str,
        top_k: int = 5,
        history: list[dict] | None = None,
        session_id: str | None = None,
        document_ids: list[UUID] | None = None,
    ) -> SearchResponse:
        """保留 JSON 调用的同步入口，共用相同的回答与缓存逻辑。"""
        response = self._prepare_search(query, top_k, history, session_id, document_ids)
        return _run_async(response) if inspect.isawaitable(response) else response

    async def search_async(
        self,
        query: str,
        top_k: int = 5,
        history: list[dict] | None = None,
        session_id: str | None = None,
        document_ids: list[UUID] | None = None,
        *,
        on_metadata: Callable[[SearchResponse], Awaitable[None]] | None = None,
        on_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> SearchResponse:
        """在线程中完成阻塞检索，再在请求事件循环中流式生成。"""
        preparation = asyncio.create_task(
            asyncio.to_thread(
                self._prepare_search,
                query,
                top_k,
                history,
                session_id,
                document_ids,
                on_metadata=on_metadata,
                on_delta=on_delta,
            )
        )
        try:
            response = await asyncio.shield(preparation)
        except asyncio.CancelledError:
            # 线程不能强制停止；等待读取退出后才能让请求释放数据库和客户端。
            with CancelScope(shield=True):
                try:
                    response = await preparation
                except Exception as exc:
                    self._logger.warning(
                        "search_cancelled_preparation_failed", error_type=type(exc).__name__
                    )
                else:
                    if inspect.iscoroutine(response):
                        response.close()
            raise
        return await response if inspect.isawaitable(response) else response

    def _prepare_search(
        self,
        query: str,
        top_k: int = 5,
        history: list[dict] | None = None,
        session_id: str | None = None,
        document_ids: list[UUID] | None = None,
        *,
        on_metadata: Callable[[SearchResponse], Awaitable[None]] | None = None,
        on_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> SearchResponse | Awaitable[SearchResponse]:
        """按回答策略检索、读取资料或直接生成，统一保留缓存和错误语义。"""
        t0 = time.perf_counter()
        self._document_ids = (
            sorted(set(document_ids), key=str) if document_ids is not None else None
        )
        validate_scope(self._session, self._owner_user_id, self._document_ids)
        scope = ",".join(map(str, self._document_ids)) if self._document_ids is not None else "all"
        namespace = f"{self._cache_scope}:docs:{scope}"
        intent = route_answer(query, has_scope=self._document_ids is not None)
        if intent == "summary":
            revision = summary_revision(self._session, self._owner_user_id, self._document_ids)
            namespace += f":summary:{revision}"

        self._logger.info("search_start", query=query, top_k=top_k)

        # 解析会话 ID
        resolved_session_id = self._resolve_session_id(session_id, history)
        rewrite_session_id = resolved_session_id
        if resolved_session_id is not None:
            resolved_session_id = f"{namespace}:{resolved_session_id}"

        # 计算 history digest（用于缓存键，确保不同对话历史产生不同缓存键）
        history_digest = self._compute_history_digest(history)

        # 生成审计追踪 ID（端到端追踪）
        audit_trail_id = (
            self._audit_trail.generate_id()  # type: ignore[union-attr]
            if self._audit_trail is not None
            else None
        )

        # -1. L1 搜索响应缓存查找（会话绑定精确匹配）
        #     仅当 resolved_session_id 非 None（可信身份）时使用缓存；
        #     不可信身份（匿名无 history）跳过缓存，防止私有响应跨用户泄漏。
        if self._response_cache is not None and resolved_session_id is not None:
            cache_key = self._make_search_cache_key(
                resolved_session_id, query, top_k, history_digest
            )
            cached_response = self._response_cache.lookup(  # type: ignore[union-attr]
                resolved_session_id, cache_key
            )
            if cached_response is not None:
                self._logger.info(
                    "search_response_cache_hit",
                    session_id=resolved_session_id,
                    query=query,
                    top_k=top_k,
                    audit_trail_id=audit_trail_id,
                )
                # 更新缓存响应中的审计追踪 ID（反映本次请求的 trace）
                # 同时将 rewrite_info.cache_hit 置为 True：
                #   响应来自缓存，其内部的 rewrite_info 也就是来自缓存，
                #   前端应显示"缓存命中"而非最初的 cache_hit 状态。
                cached_response = cached_response.model_copy(
                    update={
                        "audit_trail_id": audit_trail_id,
                        "rewrite_info": (
                            cached_response.rewrite_info.model_copy(update={"cache_hit": True})
                            if cached_response.rewrite_info is not None
                            else None
                        ),
                    }
                )
                return cached_response

        async def finish(
            *,
            mode,
            status,
            rows=None,
            vector=None,
            total=0,
            rewrite=None,
            coverage=None,
            guidance=None,
        ):
            rows = rows or []
            results = self._build_results(rows, len(rows) if mode == "summary" else top_k)
            response = SearchResponse(
                query=query,
                query_embedding_preview=(vector or [])[:5],
                embedding_model=self._embedding_adapter.config.model,
                embedding_dimensions=self._embedding_adapter.config.dimensions,
                top_k=top_k,
                total_searched=total,
                searched_document_count=len({r.parsed_document_id for r in results}),
                search_time_ms=(time.perf_counter() - t0) * 1000,
                rewrite_info=rewrite,
                results=results,
                answer="",
                chat_model=self._chat_config.model if mode != "clarification" else None,
                audit_trail_id=audit_trail_id,
                answer_mode=mode,
                retrieval_status=status,
                summary_coverage=coverage,
            )
            if on_metadata is not None and mode != "clarification":
                await on_metadata(response)
            if mode == "clarification":
                answer, tokens, model, messages, error, incomplete = (
                    guidance or clarification(status),
                    None,
                    None,
                    [],
                    None,
                    False,
                )
            else:
                answer, tokens, model, messages, error, incomplete = await self._generate_answer(
                    query,
                    rows,
                    history=history,
                    mode=mode,
                    partial=bool(coverage and coverage.truncated),
                    on_delta=on_delta,
                )
            response = response.model_copy(
                update={
                    "answer": answer,
                    "answer_incomplete": incomplete,
                    "answer_tokens": tokens,
                    "chat_model": model,
                    "prompt_messages": messages,
                    "chat_config_snapshot": self._chat_config.snapshot() if model else None,
                    "generation_error": error,
                    "search_time_ms": (time.perf_counter() - t0) * 1000,
                }
            )
            if (
                self._response_cache is not None
                and resolved_session_id is not None
                and error is None
                and not incomplete
                and status != "unavailable"
                and mode != "clarification"
            ):
                cache_key = self._make_search_cache_key(
                    resolved_session_id, query, top_k, history_digest
                )
                self._response_cache.store(resolved_session_id, cache_key, response)
            self._logger.info(
                "search_complete",
                answer_mode=mode,
                retrieval_status=status,
                result_count=len(results),
                total_searched=total,
                search_time_ms=round(response.search_time_ms, 2),
                searched_document_count=response.searched_document_count,
                audit_trail_id=audit_trail_id,
            )
            return response

        if intent == "general":
            return finish(mode="general", status="skipped")
        if intent == "summary":
            context = build_summary_context(self._session, self._owner_user_id, self._document_ids)
            if not context.rows:
                return finish(mode="clarification", status="skipped", guidance=context.guidance)
            return finish(
                mode="summary", status="matched", rows=context.rows, coverage=context.coverage
            )

        # 0. 查询重写（如果配置了 QueryRewriter）
        rewrite_info: RewriteInfo | None
        query_for_embedding = query

        if self._query_rewriter is not None:
            rewrite_t0 = time.perf_counter()
            try:
                rewrite_result = self._query_rewriter.rewrite(  # type: ignore[union-attr]
                    query,
                    session_id=rewrite_session_id,
                    history=history,
                    cache_namespace=namespace,
                )
                # QueryRewriter.rewrite() is async in production, but tests use sync mocks.
                # Use _run_async() for real coroutines, pass through sync results directly.
                if inspect.isawaitable(rewrite_result):
                    rewrite_result = _run_async(rewrite_result)
                # 使用改写后的首个查询进行向量化（一致性约束：QueryRewriter 保证
                # rewritten_queries[0] 始终是 effective query，见 query_rewriter.py 中
                # "确保 effective query 始终位于 rewritten_queries[0]" 的重排序逻辑）
                if rewrite_result.rewritten_queries:
                    query_for_embedding = rewrite_result.rewritten_queries[0]["query"]
                rewrite_info = RewriteInfo(
                    original_query=rewrite_result.original_query,
                    rewritten_queries=[
                        RewrittenQuery(
                            query=r["query"],
                            strategy=r.get("strategy"),
                            duration_ms=r.get("duration_ms"),
                            tokens=r.get("tokens"),
                        )
                        for r in rewrite_result.rewritten_queries
                    ],
                    strategies_used=rewrite_result.strategies_used,
                    rewrite_time_ms=rewrite_result.rewrite_time_ms,
                    cache_hit=rewrite_result.cache_hit,
                    rewrite_model=rewrite_result.rewrite_model,
                    intent=rewrite_result.intent,
                    complexity=rewrite_result.complexity,
                    cache_level=rewrite_result.cache_level,
                    quality_scores=(
                        QualityScores(**dataclasses.asdict(rewrite_result.quality_scores))
                        if rewrite_result.quality_scores is not None
                        else None
                    ),
                    backtrack_triggered=rewrite_result.backtrack_triggered,
                    backtrack_strategy=rewrite_result.backtrack_strategy,
                )
            except Exception as exc:
                self._logger.warning("query_rewrite_failed", error=str(exc))
                rewrite_info = RewriteInfo(
                    original_query=query,
                    rewritten_queries=[],
                    strategies_used=[],
                    rewrite_time_ms=(time.perf_counter() - rewrite_t0) * 1000,
                    cache_hit=False,
                    error=str(exc),
                )
        else:
            # 未配置重写时返回 null，前端据此区分"功能未启用"与"重写尝试但无产出"
            rewrite_info = None

        # 1. 查询向量化（使用改写后的查询或原始查询）
        try:
            embedding_result = self._embedding_adapter.embed_single(query_for_embedding)
        except EmbeddingAPIError:
            return finish(
                mode="clarification" if intent == "private" else "general",
                status="unavailable",
                rewrite=rewrite_info,
            )
        query_vector = embedding_result.embedding
        total_searched = self._count_total_embeddings()
        if total_searched == 0:
            return finish(
                mode="clarification" if intent == "private" else "general",
                status="empty",
                vector=query_vector,
                rewrite=rewrite_info,
            )

        # 4. pgvector 跨文档检索
        candidate_count = min(50, max(top_k, 20)) if self._rerank_adapter else top_k
        rows = self._vector_search(query_vector, candidate_count)

        # 4a. 按相似度阈值过滤：仅保留 cosine_distance <= threshold 的结果。
        #     当阈值设为 0 时禁用过滤（保留所有结果）。
        #     理由：pgvector 的 cosine_distance 总是返回最近邻，即使语义上完全不相关，
        #     因此必须设阈值来防止无关分块（如 "[TOC]" 标记、目录结构等）被纳入上下文，
        #     避免 LLM 基于噪声产生幻觉（参考 Anthropic Cookbook / LangChain 最佳实践）。
        if self._similarity_threshold > 0:
            rows = self._filter_by_similarity(rows, self._similarity_threshold)

        # 4b. 最低分数阈值检查（第二道防线）：即使有分块通过了相似度阈值，
        #     如果最优分块的余弦距离仍然较高（即语义上不够接近），
        #     说明知识库中没有真正相关的内容，应返回空结果。
        #     这是防止 LLM 基于弱相关内容产生幻觉的关键防线。
        #     设 0 表示禁用此检查。
        if self._min_score_threshold > 0 and len(rows) > 0:
            best_score = min(r.score for r in rows)
            if best_score > self._min_score_threshold:
                self._logger.info(
                    "search_best_score_above_min_threshold",
                    best_score=round(best_score, 6),
                    min_score_threshold=self._min_score_threshold,
                    filtered_count=len(rows),
                )
                rows = []

        if self._rerank_adapter and rows:
            try:
                indices = self._rerank_adapter.rank(
                    query,
                    [
                        row.DocumentChunk.contextualized_text or row.DocumentChunk.text or ""
                        for row in rows
                    ],
                    top_k,
                )
                rows = [rows[index] for index in indices]
            except RerankError:
                self._logger.warning("search_rerank_unavailable")
                rows = rows[:top_k]

        rows = [
            row
            for row in rows
            if not self._is_noise_chunk(
                row.DocumentChunk.contextualized_text or row.DocumentChunk.text or ""
            )
        ][:top_k]
        if not rows:
            return finish(
                mode="clarification" if intent == "private" else "general",
                status="no_match",
                vector=query_vector,
                total=total_searched,
                rewrite=rewrite_info,
            )
        return finish(
            mode="rag",
            status="matched",
            rows=rows,
            vector=query_vector,
            total=total_searched,
            rewrite=rewrite_info,
        )

    # ── private: count / search / build ─────────────────────────────

    def _count_total_embeddings(self) -> int:
        """Return the total number of embedding vectors in the database."""
        stmt = (
            select(func.count())
            .select_from(DocumentEmbedding)
            .join(ParsedDocument, DocumentEmbedding.parsed_document_id == ParsedDocument.id)
            .join(UploadedFile, ParsedDocument.uploaded_file_id == UploadedFile.id)
            .where(
                DocumentEmbedding.owner_user_id == self._owner_user_id,
                ParsedDocument.owner_user_id == self._owner_user_id,
                UploadedFile.owner_user_id == self._owner_user_id,
                UploadedFile.deleted_at.is_(None),
            )
        )
        if self._document_ids is not None:
            stmt = stmt.where(ParsedDocument.id.in_(self._document_ids))
        result = self._session.exec(stmt)
        count = result.first()
        return count or 0

    @staticmethod
    def _filter_by_similarity(rows, threshold: float) -> list:
        """Filter *rows* to only those whose cosine distance is ≤ *threshold*.

        Cosine distance in pgvector ranges [0, 2]:
        - 0 = identical vectors
        - 1 = orthogonal vectors
        - 2 = opposite vectors

        Only rows with ``score <= threshold`` are retained.  When *threshold*
        is 0 this method is never called — the caller short-circuits.
        """
        filtered = [r for r in rows if r.score <= threshold]
        return filtered

    def _vector_search(self, query_vector: list[float], top_k: int):
        """Execute a pgvector cosine-distance search across **all** documents.

        Joins ``DocumentEmbedding`` → ``DocumentChunk`` → ``ParsedDocument`` →
        ``UploadedFile`` so every row carries the full metadata required by the
        ``SearchResult`` schema.
        """
        distance_expr = DocumentEmbedding.embedding_vector.cosine_distance(query_vector)

        stmt = (
            select(
                DocumentEmbedding,
                DocumentChunk,
                ParsedDocument,
                UploadedFile.original_filename.label("document_name"),
                distance_expr.label("score"),
            )
            .join(DocumentChunk, DocumentEmbedding.chunk_id == DocumentChunk.id)
            .join(
                ParsedDocument,
                DocumentEmbedding.parsed_document_id == ParsedDocument.id,
            )
            .join(
                UploadedFile,
                ParsedDocument.uploaded_file_id == UploadedFile.id,
            )
            .where(
                DocumentEmbedding.owner_user_id == self._owner_user_id,
                DocumentChunk.owner_user_id == self._owner_user_id,
                ParsedDocument.owner_user_id == self._owner_user_id,
                UploadedFile.owner_user_id == self._owner_user_id,
                UploadedFile.deleted_at.is_(None),
            )
            .order_by(distance_expr.asc())
            .limit(top_k)
        )

        if self._document_ids is not None:
            stmt = stmt.where(ParsedDocument.id.in_(self._document_ids))
        return self._session.exec(stmt).all()

    def _build_results(self, rows, top_k: int) -> list[SearchResult]:
        """Convert raw DB rows into ``SearchResult`` objects.

        Text fields are truncated to **300 characters** to keep the API
        response compact.  The full text is still available in the prompt
        (``_assemble_prompt`` uses the untruncated source directly from
        ``rows``).

        The result count is clamped to *top_k* as a safety measure — the
        database ``LIMIT`` is the primary enforcement, but this guards
        against edge cases in test mocks or driver bugs.
        """
        results: list[SearchResult] = []
        for rank, row in enumerate(rows[:top_k], start=1):
            # Rows are SQLAlchemy Row objects — attribute access works for
            # both real ORM instances and the SimpleNamespace fakes used in tests.
            embedding = row.DocumentEmbedding
            chunk = row.DocumentChunk

            text = (chunk.text or "")[:300]
            contextualized_text = (chunk.contextualized_text or "")[:300]

            results.append(
                SearchResult(
                    rank=rank,
                    score=round(row.score, 6),
                    chunk_id=embedding.chunk_id,
                    parsed_document_id=embedding.parsed_document_id,
                    document_name=row.document_name,
                    sequence_index=embedding.sequence_index,
                    text=text,
                    contextualized_text=contextualized_text,
                    token_count=chunk.token_count,
                    heading_path=chunk.heading_path,
                    page_numbers=chunk.page_numbers,
                )
            )
        return results

    # ── private: LLM generation ─────────────────────────────────────

    async def _generate_answer(
        self,
        query: str,
        rows,
        history: list[dict] | None = None,
        *,
        mode: str = "rag",
        partial: bool = False,
        on_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[
        str,  # answer
        AnswerTokens | None,  # answer_tokens
        str | None,  # chat_model
        list[dict],  # prompt_messages
        str | None,  # generation_error
        bool,  # answer_incomplete
    ]:
        """Attempt LLM generation; degrade gracefully when not configured or on failure.

        Returns ``(answer, answer_tokens, chat_model, prompt_messages,
        generation_error, answer_incomplete)``. On the happy path ``generation_error`` is ``None``;
        when non-``None`` it signals that ``answer`` is a degradation fallback
        rather than an LLM-authored response.

        LLM 调用采用 **异步流式 + 首 token 超时 + 整体超时兜底** 三层防护：

        1. **首 token 超时**（``chat_first_token_timeout``，默认 10s）：
           首个 token 未在此时间内到达 → 判定服务不可用，快速降级。
        2. **流式收集**：一旦首 token 到达即表明模型在工作，后续收集无单独时限，
           避免因生成慢而被误杀。
        3. **整体超时兜底**（``generation_timeout``，默认 120s）：
           初次生成、长度续写和 403 重试共享截止时间。

        When a **403** is received from the upstream API (common with API proxies
        that have content-safety filters), the method retries once with the
        system prompt merged into the user message.  This avoids the ``system``
        role — which some proxies flag — while preserving the same instructions.

        Args:
            query: 当前用户查询。
            rows: 检索到的分块行列表。
            history: 可选的多轮对话历史（role + content 消息列表），
                     仅 ``user`` 和 ``assistant`` 角色会被注入 prompt。
        """
        # Chat 未配置 → 拒绝生成，检索结果完整保留
        if not self._chat_config.model:
            self._logger.info("chat_generation_skipped", reason="chat_model_empty")
            return (
                _CHAT_DISABLED_ANSWER,
                None,
                None,
                [],
                _CHAT_DISABLED_ERROR,
                False,
            )

        # ── 熔断器检查：已断开 → 跳过 LLM 调用，直接返回降级文本 ──
        if self._circuit_breaker is not None and not self._circuit_breaker.before_call():
            self._logger.warning(
                "chat_circuit_breaker_open",
                query=query,
                failure_count=self._circuit_breaker.failure_count,
            )
            return (
                _CHAT_FAILED_ANSWER,
                None,
                None,
                [],
                "Circuit breaker open — chat generation skipped",
                False,
            )

        # 组装 prompt（使用分块完整文本，非截断版本）
        messages = self._assemble_prompt(query, rows, history=history, mode=mode, partial=partial)
        deadline = asyncio.get_running_loop().time() + self._chat_config.generation_timeout
        stream_failed = False

        async def _try_generate(msgs: list[dict]) -> tuple:
            """长度结束时有界续写；后续失败仍保留已经收到的正文。"""
            nonlocal stream_failed
            answer = ""
            tokens = AnswerTokens(prompt_tokens=0, completion_tokens=0, total_tokens=0)
            model = None
            current_messages = msgs
            received: list[str] = []

            async def receive_delta(text: str) -> None:
                received.append(text)
                if on_delta is not None:
                    await on_delta(text)

            for attempt in range(_MAX_ANSWER_CONTINUATIONS + 1):
                received.clear()
                try:
                    remaining = deadline - asyncio.get_running_loop().time()
                    chat_result = await asyncio.wait_for(
                        self._chat_adapter.generate_async(
                            current_messages,
                            **({"on_delta": receive_delta} if on_delta is not None else {}),
                        ),
                        timeout=max(0, remaining),
                    )
                except (TimeoutError, ChatAPIError) as exc:
                    error = (
                        ChatAPIError("LLM generation timed out")
                        if isinstance(exc, TimeoutError)
                        else exc
                    )
                    answer += "".join(received)
                    if answer.strip():
                        stream_failed = True
                        self._logger.warning("chat_continuation_failed", attempt=attempt)
                        return (
                            answer,
                            tokens if tokens.total_tokens else None,
                            model or self._chat_config.model,
                            current_messages,
                            None,
                            True,
                        )
                    return None, None, None, current_messages, error, False

                answer += chat_result.content
                model = chat_result.model
                tokens.prompt_tokens += chat_result.prompt_tokens
                tokens.completion_tokens += chat_result.completion_tokens
                tokens.total_tokens += chat_result.total_tokens
                reason = chat_result.finish_reason
                self._logger.info(
                    "chat_generation_finished",
                    finish_reason=reason,
                    attempt=attempt,
                    completion_tokens=chat_result.completion_tokens,
                )
                if reason != "length" or attempt == _MAX_ANSWER_CONTINUATIONS:
                    incomplete = reason != "stop" or (
                        attempt > 0 and not chat_result.content.strip()
                    )
                    return answer, tokens, model, current_messages, None, incomplete
                current_messages = [
                    *msgs,
                    *([{"role": "assistant", "content": answer}] if answer.strip() else []),
                    {"role": "user", "content": _CONTINUE_PROMPT},
                ]

        result = await _try_generate(messages)
        answer, answer_tokens, chat_model, final_messages, gen_error, incomplete = result

        if gen_error is not None and gen_error.status_code == 403:
            # ── 403 fallback：合并 system prompt 到 user message 中重试 ──
            # 部分 API 代理对 system 角色消息执行内容审查拦截。
            # 将系统指令内联到 user 消息中可以绕过此限制，
            # 同时保持相同的指令语义（大多数模型对两种形式一视同仁）。
            merged_messages = self._assemble_prompt_merged(
                query, rows, history=history, mode=mode, partial=partial
            )
            self._logger.info(
                "chat_403_retry_merged",
                original_message_count=len(messages),
                merged_message_count=len(merged_messages),
                total_chars=sum(len(m["content"]) for m in merged_messages),
            )
            result = await _try_generate(merged_messages)
            answer, answer_tokens, chat_model, final_messages, gen_error, incomplete = result

        if gen_error is not None:
            # 记录完整错误上下文以辅助排查（如 API 中转站内容审查拦截）
            self._logger.warning(
                "chat_generation_failed",
                error=str(gen_error),
                status_code=gen_error.status_code,
                request_id=gen_error.request_id,
                response_body=gen_error.response_body,
                user_query=query,
                context_chunk_count=len(rows),
                total_prompt_chars=sum(len(m["content"]) for m in final_messages),
            )
            # ── 通知熔断器：LLM 调用失败 ──
            if self._circuit_breaker is not None:
                self._circuit_breaker.on_failure()
            return (
                _CHAT_FAILED_ANSWER,
                None,
                None,
                [],
                str(gen_error),
                False,
            )

        # ── 空内容检查：LLM 成功返回但未产生任何可用文本 ──
        # 推理类模型（如 deepseek-v4-pro）流式输出时可能把推理过程放进
        # ``reasoning_content`` 字段，而最终答案 ``content`` 为空；或 token
        # 预算耗尽导致 answer 为空串。若以 ``generation_error=None`` 返回空
        # answer，前端 AnswerPanel 会误判为"仍在等待生成"，无限显示
        # "等待 AI 回答生成..."。这里将其视为一次生成失败并降级。
        if not answer or not answer.strip():
            self._logger.warning(
                "chat_generation_empty_content",
                user_query=query,
                context_chunk_count=len(rows),
            )
            if self._circuit_breaker is not None:
                self._circuit_breaker.on_failure()
            return (
                _CHAT_FAILED_ANSWER,
                None,
                None,
                [],
                "LLM returned empty content",
                False,
            )

        if self._circuit_breaker is not None:
            if stream_failed:
                self._circuit_breaker.on_failure()
            else:
                self._circuit_breaker.on_success()
        return (
            answer or "",
            answer_tokens,
            chat_model,
            final_messages,
            None,
            incomplete,
        )

    def _assemble_prompt(
        self,
        query: str,
        rows,
        history: list[dict] | None = None,
        *,
        mode: str = "rag",
        partial: bool = False,
    ) -> list[dict]:
        """Build the ``messages`` array sent to the LLM.

        **Context assembly rules** (per spec):

        1. ``contextualized_text`` is preferred over ``text`` — it contains
           heading paths, preceding/following context summaries that reduce
           hallucinations (ref: Anthropic Contextual Retrieval).
        2. Source metadata (document name, heading path, page numbers) is
           included in a structured format to help the LLM cite sources.
        3. Noise chunks (e.g. "[TOC]" markers, empty/whitespace-only text)
           are skipped so they don't pollute the LLM context.

        **History injection** (multi-turn support):

        When *history* is provided, only ``user`` and ``assistant`` role
        messages are injected between the system instruction and the current
        user message.  ``system``-role entries are filtered out to prevent
        injection of conflicting instructions.  Each history message is
        truncated to ``_HISTORY_MESSAGE_MAX_CHARS`` as a defense-in-depth
        measure against overlong histories.
        """
        context_parts: list[str] = []

        for i, row in enumerate(rows, start=1):
            chunk = row.DocumentChunk

            # 优先使用上下文增强文本，降级为原始文本
            chunk_text = chunk.contextualized_text or chunk.text or ""

            # 跳过噪声分块：[TOC] 标记、空白文本等
            if self._is_noise_chunk(chunk_text):
                self._logger.info(
                    "skipping_noise_chunk",
                    chunk_index=i,
                    document_name=getattr(row, "document_name", "unknown"),
                )
                continue

            # 结构化来源元数据
            source_info = f"来源: {row.document_name}"
            if mode == "summary":
                source_info += (
                    f", 文档 ID: {row.DocumentEmbedding.parsed_document_id}"
                    f", 分块 ID: {row.DocumentEmbedding.chunk_id}"
                )
            heading_path = getattr(chunk, "heading_path", None)
            if heading_path:
                source_info += f", 标题路径: {' > '.join(heading_path)}"
            page_numbers = getattr(chunk, "page_numbers", None)
            if page_numbers:
                page_str = ", ".join(str(p) for p in page_numbers)
                source_info += f", 页码: {page_str}"

            context_parts.append(f"[分块 {i}]\n{source_info}\n内容: {chunk_text}\n")

        context = "\n".join(context_parts)
        user_content = (
            query
            if mode == "general"
            else USER_PROMPT_TEMPLATE.format(context=context, query=query)
        )

        # 构建 messages 数组：
        #   1. system 指令
        #   2. 历史消息（仅 user / assistant 角色）
        #   3. 当前 user 消息（含上下文 + 查询）
        messages: list[dict] = [{"role": "system", "content": system_prompt(mode, partial=partial)}]
        messages.extend(self._format_history_messages(history))
        messages.append({"role": "user", "content": user_content})
        return messages

    def _assemble_prompt_merged(
        self,
        query: str,
        rows,
        history: list[dict] | None = None,
        *,
        mode: str = "rag",
        partial: bool = False,
    ) -> list[dict]:
        """403 重试沿用相同模式与覆盖边界，仅合并系统指令。"""
        messages = self._assemble_prompt(query, rows, history=history, mode=mode, partial=partial)
        return messages[1:-1] + [
            {
                "role": "user",
                "content": f"{messages[0]['content']}\n\n---\n\n{messages[-1]['content']}",
            }
        ]

    # ── private: content quality ─────────────────────────────────

    @staticmethod
    def _format_history_messages(history: list[dict] | None) -> list[dict]:
        """Format conversation history into Chat Completions messages.

        Only ``user`` and ``assistant`` role entries are retained —
        ``system``-role entries are filtered out to prevent injection of
        conflicting instructions.  Each message's content is truncated to
        ``_HISTORY_MESSAGE_MAX_CHARS`` as a defense-in-depth measure.
        """
        if not history:
            return []

        messages: list[dict] = []
        for msg in history:
            role = msg.get("role")
            if role not in ("user", "assistant"):
                continue
            content = str(msg.get("content", ""))
            if len(content) > _HISTORY_MESSAGE_MAX_CHARS:
                content = content[:_HISTORY_MESSAGE_MAX_CHARS]
            messages.append({"role": role, "content": content})
        return messages

    @staticmethod
    def _is_noise_chunk(text: str) -> bool:
        """Check if *text* is a noise chunk that should not enter the LLM context.

        Noise chunks include:
        - Empty or whitespace-only text
        - Pure ``[TOC]`` markers (Markdown table-of-contents placeholders)
        - Text that is solely structural markup with no semantic content

        Returns ``True`` when the chunk should be **skipped**.
        """
        if not text or not text.strip():
            return True

        stripped = text.strip()

        # 纯 [TOC] 标记 —— Markdown/Prose 目录占位符
        if stripped.upper() in {"[TOC]", "[TOC] [TOC]", "[目录]", "[[TOC]]"}:
            return True

        # 仅由空白和 [TOC] 标记组成的文本（如 "[TOC]\n[TOC]\n"）
        cleaned = stripped.replace("[TOC]", "").replace("[toc]", "").replace("[目录]", "").strip()
        return not cleaned
