"""流水线存取验证响应模型 —— 结构化描述「向量 → 分块 → 文档」全链路验证结果。

本模块定义 GET /api/parsed-documents/{parsed_document_id}/pipeline-verification
的 JSON 响应结构，供 Pydantic 序列化与前端类型化消费。
"""

from uuid import UUID

from pydantic import BaseModel


class DocumentChainInfo(BaseModel):
    """验证请求所涉文档的元信息，从 parsed_document + uploaded_file 组装。"""

    parsed_document_id: UUID
    title: str | None
    original_filename: str
    content_type: str | None
    byte_size: int


class PipelineStageInfo(BaseModel):
    """单个 pipeline 阶段的作业状态。"""

    id: UUID
    status: str


class ParseJobStage(PipelineStageInfo):
    """解析阶段 —— 仅保留状态信息。"""

    pass


class ChunkJobStage(PipelineStageInfo):
    """分块阶段 —— 额外携带分块器名称和分块数量。"""

    chunker_name: str
    chunk_count: int


class EmbeddingJobStage(PipelineStageInfo):
    """向量化阶段 —— 额外携带嵌入模型、维度和向量数量。"""

    model: str
    dimensions: int
    embedding_count: int


class PipelineInfo(BaseModel):
    """pipeline 三阶段作业状态容器。"""

    parse_job: ParseJobStage | None
    chunk_job: ChunkJobStage | None
    embedding_job: EmbeddingJobStage | None


class VerificationCheck(BaseModel):
    """单条完整性检查结果。"""

    name: str
    passed: bool
    message: str


class VerificationSummary(BaseModel):
    """7 项完整性检查汇总。"""

    passed: bool
    total_checks: int
    passed_checks: int
    checks: list[VerificationCheck]


class ChunkInfo(BaseModel):
    """分块信息 —— 嵌入在 pair 中的 chunk 侧数据。

    文本字段均为截断版本（前端展示用），完整文本可通过
    GET /api/document-chunks/{chunk_id}/ 获取。
    """

    id: UUID
    text: str | None
    contextualized_text: str | None
    text_source: str  # "inline" | "file" | "unavailable"
    token_count: int | None
    heading_path: list[str] | None
    page_numbers: list[int] | None


class EmbeddingInfo(BaseModel):
    """向量信息 —— 嵌入在 pair 中的 embedding 侧数据。

    vector_preview 仅返回前 5 维，完整向量可通过
    GET /api/document-chunks/{chunk_id}/embedding 获取。
    """

    id: UUID
    model: str
    dimensions: int
    vector_preview: list[float]
    token_count: int | None


class ChunkEmbeddingPairResponse(BaseModel):
    """一个分块与对应向量的匹配对。

    在正常情况下 chunk 和 embedding 均非空。
    存在孤儿 embedding 时 chunk 为 None，存在孤儿 chunk 时 embedding 为 None。
    pair 列表按 sequence_index 升序排列。
    """

    sequence_index: int
    chunk: ChunkInfo | None
    embedding: EmbeddingInfo | None


class VerificationStats(BaseModel):
    """验证统计摘要 —— 从 pairs 与 checks 聚合，供前端概览面板使用。"""

    total_pairs: int
    total_chunk_tokens: int
    total_embedding_tokens: int
    inline_text_count: int
    file_storage_text_count: int
    embedding_dimensions: int | None
    embedding_model: str | None


class PipelineVerificationResponse(BaseModel):
    """GET /api/parsed-documents/{parsed_document_id}/pipeline-verification 的完整响应体。"""

    document: DocumentChainInfo
    pipeline: PipelineInfo
    verification: VerificationSummary
    pairs: list[ChunkEmbeddingPairResponse]
    stats: VerificationStats
