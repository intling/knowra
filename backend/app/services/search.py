"""Semantic search orchestration: vectorize → retrieve → generate → respond.

The ``SearchService`` is the core of the RAG pipeline.  It receives a natural-language
query, vectorises it with ``EmbeddingAdapter``, retrieves the top-K most similar chunks
via pgvector cosine distance, assembles a prompt, calls the LLM, and returns a fully
populated ``SearchResponse``.
"""

import time

from sqlmodel import Session, func, select

from app.core.logging import get_logger
from app.models.document_chunking import DocumentChunk
from app.models.document_embedding import DocumentEmbedding
from app.models.document_parsing import ParsedDocument
from app.models.uploaded_file import UploadedFile
from app.schemas.search import AnswerTokens, SearchResponse, SearchResult
from app.services.chat_adapter import ChatAdapter, ChatAPIError
from app.services.chat_config import ChatConfig
from app.services.embedding_adapter import EmbeddingAdapter

# ── prompt 模板 ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
你是一个基于知识库文档的 AI 助手。请根据提供的上下文信息回答用户的问题，并遵循以下规则：

1. **仅根据上下文回答**：只使用提供的文档片段来构建你的回答。\
禁止使用任何训练数据或外部知识。
2. **无法回答时的严格规则**：如果提供的上下文不足以回答问题，\
你的整个回复必须且仅能是以下这句话（含句号），\
**不得添加任何其他文字**（包括但不限于原因说明、来源引用、建议、\
道歉、检索过程描述、文档类型列举等）：
根据现有文档内容，无法回答此问题。
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
        min_score_threshold: float = 0.4,
    ) -> None:
        self._session = session
        self._embedding_adapter = embedding_adapter
        self._chat_adapter = chat_adapter
        self._chat_config = chat_config
        self._similarity_threshold = similarity_threshold
        self._min_score_threshold = min_score_threshold
        self._logger = get_logger(__name__)

    # ── public API ──────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 5) -> SearchResponse:
        """Execute a semantic search across all vectorised documents and (when
        configured) generate an LLM answer from the retrieved context.

        The method is the single entry point that orchestrates:

        1. Query vectorisation via ``EmbeddingAdapter.embed_single``.
        2. Full-table vector search via pgvector cosine distance.
        3. Context-to-prompt assembly.
        4. LLM generation (with graceful degradation).
        5. ``SearchResponse`` assembly.
        6. No-match early return (fixed phrase, no LLM call).
        """
        t0 = time.perf_counter()

        self._logger.info("search_start", query=query, top_k=top_k)

        # 1. 查询向量化
        embedding_result = self._embedding_adapter.embed_single(query)
        query_vector = embedding_result.embedding

        # 2. 统计总向量数（搜索空间大小）
        total_searched = self._count_total_embeddings()

        # 3. 无向量数据 → 直接返回（不调用 LLM，因为没有上下文可供推理）
        if total_searched == 0:
            return self._build_empty_response(query, query_vector, top_k, t0)

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
                    "search_best_score_below_threshold",
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
            return self._build_no_match_response(query, query_vector, top_k, t0,
                                                  total_searched)

        # 8. LLM 生成（含优雅降级）
        answer, answer_tokens, chat_model, prompt_messages, generation_error = (
            self._generate_answer(query, rows)
        )

        # 9. 组装响应
        search_time_ms = (time.perf_counter() - t0) * 1000

        self._logger.info(
            "search_complete",
            result_count=len(results),
            search_time_ms=round(search_time_ms, 2),
            total_searched=total_searched,
            searched_document_count=searched_document_count,
        )

        return SearchResponse(
            query=query,
            query_embedding_preview=query_vector[:5],
            embedding_model=self._embedding_adapter.config.model,
            embedding_dimensions=self._embedding_adapter.config.dimensions,
            top_k=top_k,
            total_searched=total_searched,
            searched_document_count=searched_document_count,
            search_time_ms=search_time_ms,
            results=results,
            answer=answer,
            answer_tokens=answer_tokens,
            chat_model=chat_model,
            prompt_messages=prompt_messages,
            chat_config_snapshot=(self._chat_config.snapshot() if chat_model else None),
            generation_error=generation_error,
        )

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
        self, query: str, rows
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
        messages = self._assemble_prompt(query, rows)

        try:
            chat_result = self._chat_adapter.generate(messages)

            answer_tokens = AnswerTokens(
                prompt_tokens=chat_result.prompt_tokens,
                completion_tokens=chat_result.completion_tokens,
                total_tokens=chat_result.total_tokens,
            )

            return (
                chat_result.content,
                answer_tokens,
                chat_result.model,
                messages,
                None,  # 正常路径无降级错误
            )
        except ChatAPIError as exc:
            self._logger.warning("chat_generation_failed", error=str(exc))
            return (
                _CHAT_FAILED_ANSWER,
                None,
                None,
                [],
                str(exc),
            )

    def _assemble_prompt(self, query: str, rows) -> list[dict]:
        """Build the ``messages`` array sent to the LLM.

        **Context assembly rules** (per spec):

        1. ``contextualized_text`` is preferred over ``text`` — it contains
           heading paths, preceding/following context summaries that reduce
           hallucinations (ref: Anthropic Contextual Retrieval).
        2. Source metadata (document name, heading path, page numbers) is
           included in a structured format to help the LLM cite sources.
        3. Noise chunks (e.g. "[TOC]" markers, empty/whitespace-only text)
           are skipped so they don't pollute the LLM context.
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

        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    # ── private: content quality ─────────────────────────────────

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
        if not cleaned:
            return True

        return False

    def _build_empty_response(
        self,
        query: str,
        query_vector: list[float],
        top_k: int,
        t0: float,
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
            results=[],
            answer=_NO_VECTOR_DATA_ANSWER,
            answer_tokens=None,
            chat_model=None,
            prompt_messages=[],
            chat_config_snapshot=None,
            generation_error=None,
        )

    # ── private: no-match response ────────────────────────────────────

    def _build_no_match_response(
        self,
        query: str,
        query_vector: list[float],
        top_k: int,
        t0: float,
        total_searched: int,
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
            results=[],
            answer=_NO_MATCH_ANSWER,
            answer_tokens=None,
            chat_model=None,
            prompt_messages=[],
            chat_config_snapshot=None,
            generation_error=None,
        )
