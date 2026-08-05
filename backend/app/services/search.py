"""Semantic search orchestration: vectorize → retrieve → generate → respond.

The ``SearchService`` is the core of the RAG pipeline.  It receives a natural-language
query, vectorises it with ``EmbeddingAdapter``, retrieves the top-K most similar chunks
via pgvector cosine distance, assembles a prompt, calls the LLM, and returns a fully
populated ``SearchResponse``.

L1 搜索响应缓存（会话绑定精确匹配）：
    当 ``response_cache`` 参数非 None 时，SearchService 会在管线开始前检查缓存，
    命中时直接返回缓存的 SearchResponse（跳过向量搜索和 LLM 生成）。
    缓存 Key = session_id + query_hash + top_k，确保相同会话内完全相同的查询
    + 相同 top_k 即时返回，大幅降低 LLM 调用成本与用户等待时间。
"""

import asyncio
import hashlib
import inspect
import time

from sqlmodel import Session, func, select

from app.core.logging import get_logger
from app.models.document_chunking import DocumentChunk
from app.models.document_embedding import DocumentEmbedding
from app.models.document_parsing import ParsedDocument
from app.models.uploaded_file import UploadedFile
from app.schemas.search import (
    AnswerTokens,
    RewriteInfo,
    RewrittenQuery,
    SearchResponse,
    SearchResult,
)
from app.services.chat_adapter import ChatAdapter, ChatAPIError
from app.services.chat_config import ChatConfig
from app.services.embedding_adapter import EmbeddingAdapter

# ── prompt 模板 ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
你是一个基于知识库文档的 AI 助手。请根据提供的上下文信息回答用户的问题，并遵循以下规则：

1. **基于上下文回答**：使用提供的文档片段来构建你的回答，\
优先引用文档中的信息而非外部知识。
2. **无法回答时的处理**：如果提供的上下文不足以回答问题，\
请直接回复以下这句话（含句号）：
根据现有文档内容，无法回答此问题。
注意：当上下文不足时，回复此句即可，无需添加原因说明、来源引用、\
建议、道歉或其他补充信息。
3. **注明信息来源**：在回答中引用具体的来源信息\
（文档名称、标题路径、页码等），让用户可以追溯答案依据。
4. **结构化格式**：使用 Markdown 格式组织你的回答，使信息层次清晰。\
"""

USER_PROMPT_TEMPLATE = """以下是从知识库中检索到的相关文档内容：

{context}

请根据以上文档内容回答用户的问题。如果文档中有可以直接引用的部分，请使用引用格式。

用户问题：{query}"""

# ── 降级提示 ────────────────────────────────────────────────────────────

_NO_MATCH_ANSWER = "根据现有文档内容，无法回答此问题。"
_NO_VECTOR_DATA_ANSWER = "知识库中暂无任何已向量化的文档。请先上传文档并完成向量化后再提问。"
_CHAT_DISABLED_ANSWER = "AI 回答生成功能未启用，请联系管理员配置对话模型。以下为检索到的相关内容。"
_CHAT_FAILED_ANSWER = "AI 回答生成失败，请稍后重试。以下为检索到的相关内容。"
_CHAT_DISABLED_ERROR = "Chat generation is disabled"

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
        embedding_adapter: EmbeddingAdapter,
        chat_adapter: ChatAdapter,
        chat_config: ChatConfig,
        similarity_threshold: float = 0.5,
        min_score_threshold: float = 0.45,
        query_rewriter: object | None = None,
        response_cache: object | None = None,
        audit_trail: object | None = None,
    ) -> None:
        self._session = session
        self._embedding_adapter = embedding_adapter
        self._chat_adapter = chat_adapter
        self._chat_config = chat_config
        self._similarity_threshold = similarity_threshold
        self._min_score_threshold = min_score_threshold
        self._query_rewriter = query_rewriter
        self._response_cache = response_cache
        self._audit_trail = audit_trail
        self._logger = get_logger(__name__)

    # ── public API ──────────────────────────────────────────────────

    @staticmethod
    def _make_search_cache_key(session_id: str, query: str, top_k: int) -> str:
        """生成搜索响应缓存的复合键。

        缓存键 = SHA-256(session_id + ":" + query + ":" + str(top_k)) 的前 16 字符。
        三方组合确保：相同会话 + 完全相同查询文本 + 相同 top_k 才能命中。
        """
        raw = f"{session_id}:{query}:{top_k}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _resolve_session_id(session_id: str | None, history: list[dict] | None) -> str:
        """解析会话标识符：显式传入优先，否则从 history 哈希派生，兜底返回 ``"__default__"``。"""
        if session_id:
            return session_id
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

    def search(
        self,
        query: str,
        top_k: int = 5,
        history: list[dict] | None = None,
        session_id: str | None = None,
    ) -> SearchResponse:
        """Execute a semantic search across all vectorised documents and (when
        configured) generate an LLM answer from the retrieved context.

        The method is the single entry point that orchestrates:

        -1. L1 response cache lookup (if configured) → instant return on hit.
        0. Query rewriting via ``QueryRewriter.rewrite`` (if configured).
        1. Query vectorisation via ``EmbeddingAdapter.embed_single``.
        2. Full-table vector search via pgvector cosine distance.
        3. Context-to-prompt assembly.
        4. LLM generation (with graceful degradation).
        5. ``SearchResponse`` assembly.
        6. No-match early return (fixed phrase, no LLM call).
        7. L1 response cache store (if configured).

        Args:
            query: 用户原始查询文本。
            top_k: 返回的最相似分块数量。
            history: 可选的多轮对话历史。
            session_id: 可选的会话标识符（用于缓存绑定）。
                        为 None 时从 history 自动派生。
        """
        t0 = time.perf_counter()

        self._logger.info("search_start", query=query, top_k=top_k)

        # 解析会话 ID
        resolved_session_id = self._resolve_session_id(session_id, history)

        # 生成审计追踪 ID（端到端追踪）
        audit_trail_id = (
            self._audit_trail.generate_id()  # type: ignore[union-attr]
            if self._audit_trail is not None
            else None
        )

        # -1. L1 搜索响应缓存查找（会话绑定精确匹配）
        if self._response_cache is not None:
            cache_key = self._make_search_cache_key(resolved_session_id, query, top_k)
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
                        "rewrite_info": cached_response.rewrite_info.model_copy(
                            update={"cache_hit": True}
                        ),
                    }
                )
                return cached_response

        # 0. 查询重写（如果配置了 QueryRewriter）
        rewrite_info: RewriteInfo
        query_for_embedding = query

        if self._query_rewriter is not None:
            rewrite_t0 = time.perf_counter()
            try:
                rewrite_result = self._query_rewriter.rewrite(  # type: ignore[union-attr]
                    query, session_id=resolved_session_id, history=history
                )
                # QueryRewriter.rewrite() is async in production, but tests use sync mocks.
                # Use asyncio.run() for real coroutines, pass through sync results directly.
                if inspect.isawaitable(rewrite_result):
                    rewrite_result = asyncio.run(rewrite_result)
                # 使用改写后的首个查询进行向量化
                if rewrite_result.rewritten_queries:
                    query_for_embedding = rewrite_result.rewritten_queries[0]["query"]
                rewrite_info = RewriteInfo(
                    original_query=rewrite_result.original_query,
                    rewritten_queries=[
                        RewrittenQuery(query=r["query"], strategy=r.get("strategy"))
                        for r in rewrite_result.rewritten_queries
                    ],
                    strategies_used=rewrite_result.strategies_used,
                    rewrite_time_ms=rewrite_result.rewrite_time_ms,
                    cache_hit=rewrite_result.cache_hit,
                    rewrite_model=rewrite_result.rewrite_model,
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
            # 未配置重写时仍返回基本 RewriteInfo，保证前端始终展示
            rewrite_info = RewriteInfo(
                original_query=query,
                rewritten_queries=[],
                strategies_used=[],
                rewrite_time_ms=0.0,
                cache_hit=False,
            )

        # 1. 查询向量化（使用改写后的查询或原始查询）
        embedding_result = self._embedding_adapter.embed_single(query_for_embedding)
        query_vector = embedding_result.embedding

        # 2. 统计总向量数（搜索空间大小）
        total_searched = self._count_total_embeddings()

        # 3. 无向量数据 → 直接返回（不调用 LLM，因为没有上下文可供推理）
        if total_searched == 0:
            response = self._build_empty_response(query, query_vector, top_k, t0, rewrite_info, audit_trail_id)
            if self._response_cache is not None:
                cache_key = self._make_search_cache_key(resolved_session_id, query, top_k)
                self._response_cache.store(resolved_session_id, cache_key, response)  # type: ignore[union-attr]
            return response

        # 4. pgvector 跨文档检索
        rows = self._vector_search(query_vector, top_k)

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

        # 5. 构建 SearchResult 列表（含文本截断，强制不超过 top_k）
        results = self._build_results(rows, top_k)

        # 6. 统计涉及的文档数
        searched_document_count = len({r.parsed_document_id for r in results})

        # 7. 无匹配结果 → 跳过 LLM，直接返回固定短语
        #    （包括：向量搜索返回零行、所有行均被阈值过滤掉）
        if len(rows) == 0:
            response = self._build_no_match_response(
                query, query_vector, top_k, t0, total_searched, rewrite_info, audit_trail_id
            )
            if self._response_cache is not None:
                cache_key = self._make_search_cache_key(resolved_session_id, query, top_k)
                self._response_cache.store(resolved_session_id, cache_key, response)  # type: ignore[union-attr]
            return response

        # 8. LLM 生成（含优雅降级）
        answer, answer_tokens, chat_model, prompt_messages, generation_error = (
            self._generate_answer(query, rows, history=history)
        )

        # 9. 组装响应
        search_time_ms = (time.perf_counter() - t0) * 1000

        self._logger.info(
            "search_complete",
            result_count=len(results),
            search_time_ms=round(search_time_ms, 2),
            total_searched=total_searched,
            searched_document_count=searched_document_count,
            audit_trail_id=audit_trail_id,
        )

        response = SearchResponse(
            query=query,
            query_embedding_preview=query_vector[:5],
            embedding_model=self._embedding_adapter.config.model,
            embedding_dimensions=self._embedding_adapter.config.dimensions,
            top_k=top_k,
            total_searched=total_searched,
            searched_document_count=searched_document_count,
            search_time_ms=search_time_ms,
            rewrite_info=rewrite_info,
            results=results,
            answer=answer,
            answer_tokens=answer_tokens,
            chat_model=chat_model,
            prompt_messages=prompt_messages,
            chat_config_snapshot=(self._chat_config.snapshot() if chat_model else None),
            generation_error=generation_error,
            audit_trail_id=audit_trail_id,
        )

        # 写入 L1 搜索响应缓存（会话绑定精确匹配）
        if self._response_cache is not None:
            cache_key = self._make_search_cache_key(resolved_session_id, query, top_k)
            self._response_cache.store(  # type: ignore[union-attr]
                resolved_session_id, cache_key, response
            )
            self._logger.debug(
                "search_response_cache_stored",
                session_id=resolved_session_id,
                query=query,
                top_k=top_k,
                audit_trail_id=audit_trail_id,
            )

        return response

    # ── private: count / search / build ─────────────────────────────

    def _count_total_embeddings(self) -> int:
        """Return the total number of embedding vectors in the database."""
        stmt = select(func.count()).select_from(DocumentEmbedding)
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
            .order_by(distance_expr.asc())
            .limit(top_k)
        )

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

    def _generate_answer(
        self, query: str, rows, history: list[dict] | None = None
    ) -> tuple[
        str,  # answer
        AnswerTokens | None,  # answer_tokens
        str | None,  # chat_model
        list[dict],  # prompt_messages
        str | None,  # generation_error
    ]:
        """Attempt LLM generation; degrade gracefully when not configured or on failure.

        Returns a 5-tuple of ``(answer, answer_tokens, chat_model, prompt_messages,
        generation_error)``.  On the happy path ``generation_error`` is ``None``;
        when non-``None`` it signals that ``answer`` is a degradation fallback
        rather than an LLM-authored response.

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
            )

        # 组装 prompt（使用分块完整文本，非截断版本）
        messages = self._assemble_prompt(query, rows, history=history)

        def _try_generate(msgs: list[dict]) -> tuple:
            """尝试调用 LLM，返回 (answer, answer_tokens, chat_model, messages, error)。"""
            try:
                chat_result = self._chat_adapter.generate(msgs)
                answer_tokens = AnswerTokens(
                    prompt_tokens=chat_result.prompt_tokens,
                    completion_tokens=chat_result.completion_tokens,
                    total_tokens=chat_result.total_tokens,
                )
                return (
                    chat_result.content,
                    answer_tokens,
                    chat_result.model,
                    msgs,
                    None,
                )
            except ChatAPIError as exc:
                return (None, None, None, msgs, exc)

        result = _try_generate(messages)
        answer, answer_tokens, chat_model, final_messages, gen_error = result

        if gen_error is not None and gen_error.status_code == 403:
            # ── 403 fallback：合并 system prompt 到 user message 中重试 ──
            # 部分 API 代理对 system 角色消息执行内容审查拦截。
            # 将系统指令内联到 user 消息中可以绕过此限制，
            # 同时保持相同的指令语义（大多数模型对两种形式一视同仁）。
            merged_messages = self._assemble_prompt_merged(query, rows, history=history)
            self._logger.info(
                "chat_403_retry_merged",
                original_message_count=len(messages),
                merged_message_count=len(merged_messages),
                total_chars=sum(len(m["content"]) for m in merged_messages),
            )
            result = _try_generate(merged_messages)
            answer, answer_tokens, chat_model, final_messages, gen_error = result

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
            return (
                _CHAT_FAILED_ANSWER,
                None,
                None,
                [],
                str(gen_error),
            )

        return (
            answer or "",
            answer_tokens,
            chat_model,
            final_messages,
            None,
        )

    def _assemble_prompt(
        self, query: str, rows, history: list[dict] | None = None
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
            heading_path = getattr(chunk, "heading_path", None)
            if heading_path:
                source_info += f", 标题路径: {' > '.join(heading_path)}"
            page_numbers = getattr(chunk, "page_numbers", None)
            if page_numbers:
                page_str = ", ".join(str(p) for p in page_numbers)
                source_info += f", 页码: {page_str}"

            context_parts.append(f"[分块 {i}]\n{source_info}\n内容: {chunk_text}\n")

        context = "\n".join(context_parts)
        user_content = USER_PROMPT_TEMPLATE.format(context=context, query=query)

        # 构建 messages 数组：
        #   1. system 指令
        #   2. 历史消息（仅 user / assistant 角色）
        #   3. 当前 user 消息（含上下文 + 查询）
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self._format_history_messages(history))
        messages.append({"role": "user", "content": user_content})
        return messages

    def _assemble_prompt_merged(
        self, query: str, rows, history: list[dict] | None = None
    ) -> list[dict]:
        """Build a **system-less** messages array for proxies that block ``system`` role.

        Identical to ``_assemble_prompt`` in content, but merges the system
        instructions into the user message as a prefix.  Most LLMs treat
        inline instructions at the top of the first user message equivalently
        to a system message.

        History messages (``user`` / ``assistant`` only) are kept as
        independent messages before the merged user message, preserving
        multi-turn conversation structure while still avoiding the ``system``
        role that some proxies flag.
        """
        # 复用 _assemble_prompt 的 context 构建逻辑，直接获取 user_content
        context_parts: list[str] = []

        for i, row in enumerate(rows, start=1):
            chunk = row.DocumentChunk
            chunk_text = chunk.contextualized_text or chunk.text or ""
            if self._is_noise_chunk(chunk_text):
                continue

            source_info = f"来源: {row.document_name}"
            heading_path = getattr(chunk, "heading_path", None)
            if heading_path:
                source_info += f", 标题路径: {' > '.join(heading_path)}"
            page_numbers = getattr(chunk, "page_numbers", None)
            if page_numbers:
                page_str = ", ".join(str(p) for p in page_numbers)
                source_info += f", 页码: {page_str}"

            context_parts.append(f"[分块 {i}]\n{source_info}\n内容: {chunk_text}\n")

        context = "\n".join(context_parts)
        user_body = USER_PROMPT_TEMPLATE.format(context=context, query=query)

        # 将系统指令内联到用户消息顶部
        merged_content = f"{SYSTEM_PROMPT}\n\n---\n\n{user_body}"

        # 构建 messages 数组：
        #   1. 历史消息（仅 user / assistant 角色，保持独立对话结构）
        #   2. 合并后的 user 消息（含系统指令 + 上下文 + 当前查询）
        messages: list[dict] = self._format_history_messages(history)
        messages.append({"role": "user", "content": merged_content})
        return messages

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

    def _build_empty_response(
        self,
        query: str,
        query_vector: list[float],
        top_k: int,
        t0: float,
        rewrite_info: RewriteInfo,
        audit_trail_id: str | None = None,
    ) -> SearchResponse:
        """Build a response for the case when **zero** embeddings exist in the DB.

        No LLM call is made — there is nothing to ground the answer on.
        """
        search_time_ms = (time.perf_counter() - t0) * 1000
        return SearchResponse(
            query=query,
            query_embedding_preview=query_vector[:5],
            embedding_model=self._embedding_adapter.config.model,
            embedding_dimensions=self._embedding_adapter.config.dimensions,
            top_k=top_k,
            total_searched=0,
            searched_document_count=0,
            search_time_ms=search_time_ms,
            rewrite_info=rewrite_info,
            results=[],
            answer=_NO_VECTOR_DATA_ANSWER,
            answer_tokens=None,
            chat_model=None,
            prompt_messages=[],
            chat_config_snapshot=None,
            generation_error=None,
            audit_trail_id=audit_trail_id,
        )

    # ── private: no-match response ────────────────────────────────────

    def _build_no_match_response(
        self,
        query: str,
        query_vector: list[float],
        top_k: int,
        t0: float,
        total_searched: int,
        rewrite_info: RewriteInfo,
        audit_trail_id: str | None = None,
    ) -> SearchResponse:
        """Build a response when embeddings exist but no chunks match the query.

        No LLM call is made — the fixed phrase is returned directly to
        guarantee no extra text, explanations, or source citations leak in.
        """
        search_time_ms = (time.perf_counter() - t0) * 1000
        return SearchResponse(
            query=query,
            query_embedding_preview=query_vector[:5],
            embedding_model=self._embedding_adapter.config.model,
            embedding_dimensions=self._embedding_adapter.config.dimensions,
            top_k=top_k,
            total_searched=total_searched,
            searched_document_count=0,
            search_time_ms=search_time_ms,
            rewrite_info=rewrite_info,
            results=[],
            answer=_NO_MATCH_ANSWER,
            answer_tokens=None,
            chat_model=None,
            prompt_messages=[],
            chat_config_snapshot=None,
            generation_error=None,
            audit_trail_id=audit_trail_id,
        )
