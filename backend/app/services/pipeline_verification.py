"""流水线存取验证服务 —— 端到端验证「向量 → 分块 → 文档」数据完整性。

本模块提供 ``PipelineVerificationService``，沿 JOIN 链路还原全链路数据，
执行 7 项完整性检查，生成结构化验证报告。
"""

from uuid import UUID

from sqlmodel import Session, col, select

from app.core.logging import get_logger
from app.models.document_chunking import (
    DocumentChunk,
    DocumentChunkJob,
    DocumentChunkJobStatus,
)
from app.models.document_embedding import (
    DocumentEmbedding,
    DocumentEmbeddingJob,
    DocumentEmbeddingJobStatus,
)
from app.models.document_parsing import DocumentParseJob, ParsedDocument
from app.models.uploaded_file import UploadedFile
from app.schemas.pipeline_verification import (
    ChunkEmbeddingPairResponse,
    ChunkInfo,
    ChunkJobStage,
    DocumentChainInfo,
    EmbeddingInfo,
    EmbeddingJobStage,
    ParseJobStage,
    PipelineInfo,
    PipelineVerificationResponse,
    VerificationCheck,
    VerificationStats,
    VerificationSummary,
)
from app.services.document_chunk_storage import ChunkArtifactStorage

logger = get_logger(__name__)

TEXT_PREVIEW_MAX_CHARS = 150
VECTOR_PREVIEW_DIMS = 5


class PipelineVerificationError(Exception):
    """流水线验证过程中的预期错误（如文档不存在、阶段缺失）。

    携带 HTTP 状态码和详细错误信息，供路由层映射为 HTTPException。
    """

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class PipelineVerificationService:
    """流水线存取验证服务 —— 只读验证「向量 → 分块 → 文档」全链路数据完整性。

    构造函数接收：
    - ``session``: 数据库会话
    - ``chunk_storage``: 分块工件文件系统存储
    """

    def __init__(self, session: Session, chunk_storage: ChunkArtifactStorage) -> None:
        self.session = session
        self.chunk_storage = chunk_storage

    # ── public API ──────────────────────────────────────────────────

    def verify(self, parsed_document_id: UUID, owner_user_id: UUID) -> PipelineVerificationResponse:
        """主入口：执行完整流水线验证并返回结构化结果。

        依次执行文档链加载、pipeline 完整性校验、chunk-embedding JOIN、
        文件系统文本解析、7 项完整性检查和结果组装。
        """
        parsed_document, uploaded_file = self._load_document_chain(
            parsed_document_id, owner_user_id
        )
        parse_job, chunk_job, embedding_job = self._validate_pipeline_complete(parsed_document_id)
        pairs_raw = self._load_chunk_embedding_pairs(chunk_job.id, embedding_job.id)
        pairs = self._resolve_chunk_texts(pairs_raw)
        checks = self._run_integrity_checks(pairs, chunk_job, embedding_job)
        return self._build_result(
            parsed_document=parsed_document,
            uploaded_file=uploaded_file,
            parse_job=parse_job,
            chunk_job=chunk_job,
            embedding_job=embedding_job,
            pairs=pairs,
            checks=checks,
        )

    # ── internal: document chain ────────────────────────────────────

    def _load_document_chain(
        self, parsed_document_id: UUID, owner_user_id: UUID
    ) -> tuple[ParsedDocument, UploadedFile]:
        """查询 parsed_document + uploaded_file 文档链，校验所有权。

        所有权通过 owner_user_id 匹配校验，确保用户只能验证自己的文档。

        Raises:
            PipelineVerificationError: 文档不存在或不属于当前用户。
        """
        parsed_document = self.session.exec(
            select(ParsedDocument).where(
                ParsedDocument.id == parsed_document_id,
                ParsedDocument.owner_user_id == owner_user_id,
            )
        ).first()
        if parsed_document is None:
            raise PipelineVerificationError(status_code=404, detail="Parsed document not found")

        uploaded_file = self.session.exec(
            select(UploadedFile).where(
                UploadedFile.id == parsed_document.uploaded_file_id,
            )
        ).first()
        if uploaded_file is None:
            raise PipelineVerificationError(status_code=404, detail="Uploaded file not found")

        logger.debug(
            "Document chain loaded",
            parsed_document_id=str(parsed_document_id),
            filename=uploaded_file.original_filename,
        )
        return parsed_document, uploaded_file

    # ── internal: pipeline validation ───────────────────────────────

    def _validate_pipeline_complete(
        self, parsed_document_id: UUID
    ) -> tuple[DocumentParseJob | None, DocumentChunkJob, DocumentEmbeddingJob]:
        """确认 parse/chunk/embedding 作业均为 succeeded。

        查找最新成功的分块作业及其对应的向量化作业。
        parse_job 可为 None（部分旧数据没有关联 parse_job）。

        Raises:
            PipelineVerificationError: 无成功的分块作业或向量化作业。
        """
        parsed_document = self.session.get(ParsedDocument, parsed_document_id)

        # 解析作业（可选 —— 旧数据可能没有）
        parse_job: DocumentParseJob | None = None
        if parsed_document is not None:
            parse_job = self.session.exec(
                select(DocumentParseJob).where(
                    DocumentParseJob.id == parsed_document.parse_job_id,
                )
            ).first()

        # 查找最新成功的分块作业
        chunk_job = self.session.exec(
            select(DocumentChunkJob)
            .where(
                DocumentChunkJob.parsed_document_id == parsed_document_id,
                DocumentChunkJob.status == DocumentChunkJobStatus.SUCCEEDED.value,
            )
            .order_by(col(DocumentChunkJob.created_at).desc())
        ).first()
        if chunk_job is None:
            raise PipelineVerificationError(
                status_code=404,
                detail="No succeeded chunk job found for this document",
            )

        # 查找最新成功的向量化作业
        embedding_job = self.session.exec(
            select(DocumentEmbeddingJob)
            .where(
                DocumentEmbeddingJob.chunk_job_id == chunk_job.id,
                DocumentEmbeddingJob.status == DocumentEmbeddingJobStatus.SUCCEEDED.value,
            )
            .order_by(col(DocumentEmbeddingJob.created_at).desc())
        ).first()
        if embedding_job is None:
            raise PipelineVerificationError(
                status_code=404,
                detail="No succeeded embedding job found for this document",
            )

        logger.debug(
            "Pipeline validation passed",
            parsed_document_id=str(parsed_document_id),
            chunk_job_id=str(chunk_job.id),
            embedding_job_id=str(embedding_job.id),
        )
        return parse_job, chunk_job, embedding_job

    # ── internal: chunk-embedding pairs ─────────────────────────────

    def _load_chunk_embedding_pairs(self, chunk_job_id: UUID, embedding_job_id: UUID) -> list[dict]:
        """JOIN chunks ↔ embeddings，返回原始 pair 数据列表。

        按 sequence_index 分别加载 chunks 和 embeddings，
        合并所有出现的 sequence_index，检测孤儿记录。
        返回的每个 dict 包含 chunk、embedding（可能为 None）和 sequence_index。
        """
        chunks = list(
            self.session.exec(
                select(DocumentChunk)
                .where(DocumentChunk.chunk_job_id == chunk_job_id)
                .order_by(DocumentChunk.sequence_index)
            ).all()
        )

        embeddings = list(
            self.session.exec(
                select(DocumentEmbedding)
                .where(
                    DocumentEmbedding.embedding_job_id == embedding_job_id,
                )
                .order_by(DocumentEmbedding.sequence_index)
            ).all()
        )

        # 建立 sequence_index → 记录 的映射
        chunk_by_seq: dict[int, DocumentChunk] = {}
        for c in chunks:
            chunk_by_seq.setdefault(c.sequence_index, c)

        embedding_by_seq: dict[int, DocumentEmbedding] = {}
        for e in embeddings:
            embedding_by_seq.setdefault(e.sequence_index, e)

        # 合并所有出现的 sequence_index
        all_indices = sorted(set(chunk_by_seq.keys()) | set(embedding_by_seq.keys()))

        pairs_raw: list[dict] = []
        for seq in all_indices:
            pairs_raw.append(
                {
                    "sequence_index": seq,
                    "chunk": chunk_by_seq.get(seq),
                    "embedding": embedding_by_seq.get(seq),
                }
            )

        logger.debug(
            "Chunk-embedding pairs loaded",
            chunk_count=len(chunks),
            embedding_count=len(embeddings),
            pair_count=len(pairs_raw),
        )
        return pairs_raw

    # ── internal: text resolution ───────────────────────────────────

    def _resolve_chunk_texts(self, pairs_raw: list[dict]) -> list[dict]:
        """为每个 pair 解析实际文本内容（内联或文件系统）。

        对单个文件读取失败进行 try/catch，标记该 chunk 文本为不可用，
        不因此中断整个验证流程（Degrade gracefully）。
        """
        for pair in pairs_raw:
            chunk = pair.get("chunk")
            if chunk is None:
                continue

            # 解析 text
            pair["_resolved_text"] = self._read_chunk_field(chunk.text, chunk.text_storage_key)
            pair["_text_source"] = self._text_source(chunk.text, chunk.text_storage_key)

            # 解析 contextualized_text
            pair["_resolved_contextualized_text"] = self._read_chunk_field(
                chunk.contextualized_text, chunk.contextualized_text_storage_key
            )
            pair["_contextualized_text_source"] = self._text_source(
                chunk.contextualized_text, chunk.contextualized_text_storage_key
            )

        return pairs_raw

    def _read_chunk_field(self, inline_value: str | None, storage_key: str | None) -> str | None:
        """读取分块字段的文本内容。

        优先返回内联值；若为 NULL 则通过 storage_key 从文件系统读取。
        文件读取失败时返回 None 并记录日志，不抛出异常。
        """
        if inline_value:
            return inline_value
        if storage_key:
            try:
                path = self.chunk_storage.path_for(storage_key)
                if path.exists():
                    return path.read_text(encoding="utf-8")
                logger.warning(
                    "Chunk artifact file not found",
                    storage_key=storage_key,
                )
            except (OSError, ValueError) as exc:
                logger.warning(
                    "Failed to read chunk artifact from file system",
                    storage_key=storage_key,
                    error=str(exc),
                )
        return None

    @staticmethod
    def _text_source(inline_value: str | None, storage_key: str | None) -> str:
        """判断文本来源：内联存储、文件系统或不可用。"""
        if inline_value:
            return "inline"
        if storage_key:
            return "file"
        return "unavailable"

    # ── internal: integrity checks ──────────────────────────────────

    def _run_integrity_checks(
        self,
        pairs: list[dict],
        chunk_job: DocumentChunkJob,
        embedding_job: DocumentEmbeddingJob,
    ) -> list[VerificationCheck]:
        """执行全部 7 项完整性检查。

        检查项：
        1. chunk_embedding_pairing  — 分块-向量一一对应
        2. dimension_consistency     — 向量维度一致
        3. sequence_continuity       — 序号连续无跳号
        4. chunk_text_availability   — 分块文本可读
        5. contextualized_text_availability — 上下文增强文本可读
        6. token_count_consistency   — Token 数有效性
        7. model_consistency         — 嵌入模型一致
        """
        checks: list[VerificationCheck] = []

        checks.append(self._check_chunk_embedding_pairing(pairs))
        checks.append(self._check_dimension_consistency(pairs, embedding_job.dimensions))
        checks.append(self._check_sequence_continuity(pairs))
        checks.append(self._check_chunk_text_availability(pairs))
        checks.append(self._check_contextualized_text_availability(pairs))
        checks.append(self._check_token_count_consistency(pairs))
        checks.append(self._check_model_consistency(pairs))

        return checks

    # 1. 分块-向量对应关系检查
    def _check_chunk_embedding_pairing(self, pairs: list[dict]) -> VerificationCheck:
        """验证所有 chunk 都有对应的 embedding，所有 embedding 都能找到对应的 chunk。

        检测两种异常：
        - 孤儿 embedding：chunk 已被删除但 embedding 未清理
        - 孤儿 chunk：向量化作业不完整，部分 chunk 未成功向量化
        """
        orphan_embeddings = [
            p for p in pairs if p.get("chunk") is None and p.get("embedding") is not None
        ]
        orphan_chunks = [
            p for p in pairs if p.get("embedding") is None and p.get("chunk") is not None
        ]

        total_pairs = len(pairs)
        if not orphan_embeddings and not orphan_chunks:
            return VerificationCheck(
                name="chunk_embedding_pairing",
                passed=True,
                message=f"{total_pairs}/{total_pairs} 分块与向量一一对应，无孤儿记录",
            )

        details: list[str] = []
        if orphan_embeddings:
            chunk_ids = [str(p["embedding"].chunk_id) for p in orphan_embeddings]
            details.append(
                f"孤儿 embedding {len(orphan_embeddings)} 条"
                f"（chunk_id: {', '.join(chunk_ids[:5])}"
                f"{'...' if len(chunk_ids) > 5 else ''}）"
            )
        if orphan_chunks:
            seqs = [str(p["sequence_index"]) for p in orphan_chunks]
            details.append(
                f"孤儿 chunk {len(orphan_chunks)} 条"
                f"（sequence_index: {', '.join(seqs[:5])}"
                f"{'...' if len(seqs) > 5 else ''}）"
            )

        return VerificationCheck(
            name="chunk_embedding_pairing",
            passed=False,
            message="；".join(details),
        )

    # 2. 向量维度一致性检查
    def _check_dimension_consistency(
        self, pairs: list[dict], expected_dimensions: int
    ) -> VerificationCheck:
        """验证每条 embedding 的 dimensions 和实际向量长度与作业声明一致。

        检查两个维度：
        - ``dimensions`` 字段值是否与 embedding_job 声明一致
        - ``embedding_json`` 实际长度是否与声明维度匹配
        """
        mismatched: list[int] = []

        for p in pairs:
            emb = p.get("embedding")
            if emb is None:
                continue
            if emb.dimensions != expected_dimensions:
                mismatched.append(p["sequence_index"])
                continue
            if emb.embedding_json is not None and len(emb.embedding_json) != expected_dimensions:
                mismatched.append(p["sequence_index"])

        valid_count = sum(
            1
            for p in pairs
            if p.get("embedding") is not None and p["embedding"].dimensions == expected_dimensions
        )

        if not mismatched:
            return VerificationCheck(
                name="dimension_consistency",
                passed=True,
                message=f"所有 {valid_count} 条向量维度均为 {expected_dimensions}",
            )

        preview = mismatched[:5]
        return VerificationCheck(
            name="dimension_consistency",
            passed=False,
            message=(
                f"维度不一致：sequence_index {preview}"
                f"{'...' if len(mismatched) > 5 else ''} "
                f"的向量维度异常（期望 {expected_dimensions}）"
            ),
        )

    # 3. 序号连续性检查
    def _check_sequence_continuity(self, pairs: list[dict]) -> VerificationCheck:
        """验证 sequence_index 从 0 开始连续递增至 N-1，无重复、无跳号。"""
        indices = [p["sequence_index"] for p in pairs]
        if not indices:
            return VerificationCheck(
                name="sequence_continuity",
                passed=True,
                message="无数据，跳过序号连续性检查",
            )

        # 检测重复
        seen: set[int] = set()
        duplicates: list[int] = []
        for i in indices:
            if i in seen:
                duplicates.append(i)
            seen.add(i)
        if duplicates:
            return VerificationCheck(
                name="sequence_continuity",
                passed=False,
                message=f"sequence_index 存在重复：{sorted(set(duplicates))}",
            )

        # 检测跳号
        sorted_indices = sorted(indices)
        expected = list(range(min(sorted_indices), max(sorted_indices) + 1))
        missing = sorted(set(expected) - set(sorted_indices))

        if missing:
            return VerificationCheck(
                name="sequence_continuity",
                passed=False,
                message=f"sequence_index 不连续，缺失序号：{missing}",
            )

        return VerificationCheck(
            name="sequence_continuity",
            passed=True,
            message=(
                f"sequence_index 从 {min(sorted_indices)} 到 {max(sorted_indices)} 连续无缺失"
            ),
        )

    # 4. 分块文本可读性检查
    def _check_chunk_text_availability(self, pairs: list[dict]) -> VerificationCheck:
        """验证所有 chunk 的 text 均可成功获取（内联或文件系统）。

        遍历所有 chunk，统计内联、文件存储和不可用的数量。
        """
        unavailable: list[int] = []
        inline_count = 0
        file_count = 0

        for p in pairs:
            if p.get("chunk") is None:
                continue
            source = p.get("_text_source", "unavailable")
            resolved = p.get("_resolved_text")
            if source == "inline":
                inline_count += 1
            elif source == "file" and resolved is not None:
                file_count += 1
            else:
                unavailable.append(p["sequence_index"])

        total = sum(1 for p in pairs if p.get("chunk") is not None)
        if not unavailable:
            return VerificationCheck(
                name="chunk_text_availability",
                passed=True,
                message=(
                    f"{total}/{total} 分块文本可读取（{inline_count} 内联 + {file_count} 文件存储）"
                ),
            )

        return VerificationCheck(
            name="chunk_text_availability",
            passed=False,
            message=(f"分块文本不可读：sequence_index {unavailable} 的文本无法获取"),
        )

    # 5. 上下文增强文本可读性检查
    def _check_contextualized_text_availability(self, pairs: list[dict]) -> VerificationCheck:
        """验证所有 chunk 的 contextualized_text 均可成功获取。

        检查逻辑与 chunk_text_availability 相同，但针对
        ``contextualized_text`` / ``contextualized_text_storage_key`` 字段。
        contextualized_text 为 None 且无 storage_key 是合法的（非必需字段），
        不算作不可用。
        """
        unavailable: list[int] = []
        inline_count = 0
        file_count = 0
        no_text_count = 0

        for p in pairs:
            if p.get("chunk") is None:
                continue
            source = p.get("_contextualized_text_source", "unavailable")
            resolved = p.get("_resolved_contextualized_text")
            if source == "inline":
                inline_count += 1
            elif source == "file" and resolved is not None:
                file_count += 1
            else:
                chunk = p["chunk"]
                # 区分：有 storage_key 但文件不可读 vs 本身就没有上下文文本
                if (
                    chunk.contextualized_text is not None
                    or chunk.contextualized_text_storage_key is not None
                ):
                    unavailable.append(p["sequence_index"])
                else:
                    no_text_count += 1

        total = sum(1 for p in pairs if p.get("chunk") is not None)
        available = total - len(unavailable) - no_text_count

        if not unavailable:
            return VerificationCheck(
                name="contextualized_text_availability",
                passed=True,
                message=(
                    f"{available}/{total} 上下文增强文本可读取"
                    f"（{inline_count} 内联 + {file_count} 文件存储"
                    f"{f' + {no_text_count} 无上下文' if no_text_count else ''}）"
                ),
            )

        return VerificationCheck(
            name="contextualized_text_availability",
            passed=False,
            message=(f"上下文增强文本不可读：sequence_index {unavailable} 的上下文文本无法获取"),
        )

    # 6. Token 数有效性检查
    def _check_token_count_consistency(self, pairs: list[dict]) -> VerificationCheck:
        """验证所有 chunk 和 embedding 的 token_count 均非 NULL 且大于 0。"""
        null_token_chunks: list[int] = []
        null_token_embeddings: list[int] = []
        zero_token_chunks: list[int] = []
        zero_token_embeddings: list[int] = []

        for p in pairs:
            chunk = p.get("chunk")
            emb = p.get("embedding")

            if chunk is not None:
                if chunk.token_count is None:
                    null_token_chunks.append(p["sequence_index"])
                elif chunk.token_count == 0:
                    zero_token_chunks.append(p["sequence_index"])

            if emb is not None:
                if emb.token_count is None:
                    null_token_embeddings.append(p["sequence_index"])
                elif emb.token_count == 0:
                    zero_token_embeddings.append(p["sequence_index"])

        problems: list[str] = []
        if null_token_chunks:
            problems.append(f"chunk token_count 为空 {len(null_token_chunks)} 条")
        if null_token_embeddings:
            problems.append(f"embedding token_count 为空 {len(null_token_embeddings)} 条")
        if zero_token_chunks:
            problems.append(f"chunk token_count 为 0 {len(zero_token_chunks)} 条")
        if zero_token_embeddings:
            problems.append(f"embedding token_count 为 0 {len(zero_token_embeddings)} 条")

        if not problems:
            return VerificationCheck(
                name="token_count_consistency",
                passed=True,
                message="所有 chunk 和 embedding 的 token_count 均有效",
            )

        return VerificationCheck(
            name="token_count_consistency",
            passed=False,
            message="；".join(problems),
        )

    # 7. 嵌入模型一致性检查
    def _check_model_consistency(self, pairs: list[dict]) -> VerificationCheck:
        """验证所有 embedding 使用相同的 model 字段值。

        同一文档的不同 chunk 使用不同模型将导致语义空间不一致，
        后续语义搜索会得到不可预期的结果。
        """
        models: set[str] = set()
        for p in pairs:
            emb = p.get("embedding")
            if emb is not None:
                models.add(emb.model)

        valid_count = sum(1 for p in pairs if p.get("embedding") is not None)
        if len(models) <= 1:
            model_name = next(iter(models), "N/A")
            return VerificationCheck(
                name="model_consistency",
                passed=True,
                message=f"所有 {valid_count} 条向量使用同一模型：{model_name}",
            )

        return VerificationCheck(
            name="model_consistency",
            passed=False,
            message=(f"发现 {len(models)} 个不同模型：{', '.join(sorted(models))}"),
        )

    # ── internal: result assembly ───────────────────────────────────

    def _build_result(
        self,
        *,
        parsed_document: ParsedDocument,
        uploaded_file: UploadedFile,
        parse_job: DocumentParseJob | None,
        chunk_job: DocumentChunkJob,
        embedding_job: DocumentEmbeddingJob,
        pairs: list[dict],
        checks: list[VerificationCheck],
    ) -> PipelineVerificationResponse:
        """组装完整的 ``PipelineVerificationResponse``。

        将各阶段数据映射为 Pydantic 响应模型，包括文档信息、
        pipeline 阶段状态、验证摘要、分块-向量对照表和统计摘要。
        """
        # 文档信息
        document = DocumentChainInfo(
            parsed_document_id=parsed_document.id,
            title=parsed_document.title,
            original_filename=uploaded_file.original_filename,
            content_type=uploaded_file.content_type,
            byte_size=uploaded_file.byte_size,
        )

        # Pipeline 阶段信息
        pipeline = PipelineInfo(
            parse_job=(
                ParseJobStage(id=parse_job.id, status=parse_job.status) if parse_job else None
            ),
            chunk_job=ChunkJobStage(
                id=chunk_job.id,
                status=chunk_job.status,
                chunker_name=chunk_job.chunker_name,
                chunk_count=chunk_job.chunk_count,
            ),
            embedding_job=EmbeddingJobStage(
                id=embedding_job.id,
                status=embedding_job.status,
                model=embedding_job.model,
                dimensions=embedding_job.dimensions,
                embedding_count=embedding_job.embedding_count,
            ),
        )

        # 验证摘要
        all_passed = all(check.passed for check in checks)
        verification = VerificationSummary(
            passed=all_passed,
            total_checks=len(checks),
            passed_checks=sum(1 for c in checks if c.passed),
            checks=checks,
        )

        # 分块-向量对照 pairs
        pair_responses = self._build_pair_responses(pairs)

        # 统计摘要
        stats = self._build_stats(pair_responses, embedding_job)

        logger.info(
            "Pipeline verification complete",
            parsed_document_id=str(parsed_document.id),
            passed=verification.passed,
            passed_checks=f"{verification.passed_checks}/{verification.total_checks}",
            total_pairs=stats.total_pairs,
        )
        return PipelineVerificationResponse(
            document=document,
            pipeline=pipeline,
            verification=verification,
            pairs=pair_responses,
            stats=stats,
        )

    def _build_pair_responses(self, pairs: list[dict]) -> list[ChunkEmbeddingPairResponse]:
        """将原始 pair 数据转换为 ``ChunkEmbeddingPairResponse`` 列表。

        文本截断至 ``TEXT_PREVIEW_MAX_CHARS`` 字符，向量截断至
        ``VECTOR_PREVIEW_DIMS`` 维，供前端对照表展示。
        """
        result: list[ChunkEmbeddingPairResponse] = []
        for p in pairs:
            chunk = p.get("chunk")
            embedding = p.get("embedding")

            chunk_info = None
            if chunk is not None:
                resolved_text = p.get("_resolved_text")
                truncated_text = resolved_text[:TEXT_PREVIEW_MAX_CHARS] if resolved_text else None
                resolved_ctx = p.get("_resolved_contextualized_text")
                truncated_ctx = resolved_ctx[:TEXT_PREVIEW_MAX_CHARS] if resolved_ctx else None

                chunk_info = ChunkInfo(
                    id=chunk.id,
                    text=truncated_text,
                    contextualized_text=truncated_ctx,
                    text_source=p.get("_text_source", "unavailable"),
                    token_count=chunk.token_count,
                    heading_path=chunk.heading_path,
                    page_numbers=chunk.page_numbers,
                )

            embedding_info = None
            if embedding is not None:
                vector_preview = (
                    embedding.embedding_json[:VECTOR_PREVIEW_DIMS]
                    if embedding.embedding_json
                    else []
                )
                embedding_info = EmbeddingInfo(
                    id=embedding.id,
                    model=embedding.model,
                    dimensions=embedding.dimensions,
                    vector_preview=vector_preview,
                    token_count=embedding.token_count,
                )

            result.append(
                ChunkEmbeddingPairResponse(
                    sequence_index=p["sequence_index"],
                    chunk=chunk_info,
                    embedding=embedding_info,
                )
            )

        return result

    @staticmethod
    def _build_stats(
        pairs: list[ChunkEmbeddingPairResponse],
        embedding_job: DocumentEmbeddingJob,
    ) -> VerificationStats:
        """聚合统计摘要，供前端概览面板使用。

        统计 pairs 总数、token 总计、内联/文件存储分布和向量元信息。
        """
        total_chunk_tokens = sum((p.chunk.token_count or 0) for p in pairs if p.chunk is not None)
        total_embedding_tokens = sum(
            (p.embedding.token_count or 0) for p in pairs if p.embedding is not None
        )
        inline_count = sum(
            1 for p in pairs if p.chunk is not None and p.chunk.text_source == "inline"
        )
        file_count = sum(1 for p in pairs if p.chunk is not None and p.chunk.text_source == "file")

        return VerificationStats(
            total_pairs=len(pairs),
            total_chunk_tokens=total_chunk_tokens,
            total_embedding_tokens=total_embedding_tokens,
            inline_text_count=inline_count,
            file_storage_text_count=file_count,
            embedding_dimensions=embedding_job.dimensions,
            embedding_model=embedding_job.model,
        )
