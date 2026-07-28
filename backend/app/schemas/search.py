"""搜索相关的 Pydantic Schema —— 请求、单条结果、回答 Token 统计与完整响应。"""

from uuid import UUID

from pydantic import BaseModel, Field

# ── 请求 ──────────────────────────────────────────────────────────────


class SearchRequest(BaseModel):
    """语义搜索请求体。

    约束（与 spec 一致）：
    - query：1–2000 字符
    - top_k：1–50，默认 5
    """

    query: str = Field(
        min_length=1,
        max_length=2000,
        description="自然语言查询文本",
        examples=["大模型在医疗领域的应用有哪些？"],
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=50,
        description="返回的最相似分块数量",
        examples=[5, 10],
    )


# ── 单条搜索结果 ──────────────────────────────────────────────────────


class SearchResult(BaseModel):
    """单条搜索结果 —— 一个召回的分块及其元数据。

    字段语义与 ``document_embeddings`` + ``parsed_documents``
    + ``document_chunks`` 联合查询结果一致。
    """

    rank: int = Field(description="全局排名（1-based，按余弦距离升序）")
    score: float = Field(description="余弦距离分数（越小越相似）")
    chunk_id: UUID = Field(description="分块 ID")
    parsed_document_id: UUID = Field(description="来源解析文档 ID")
    document_name: str = Field(description="来源文档名称")
    sequence_index: int = Field(description="分块在文档内的序号")
    text: str = Field(description="分块文本（截断至 300 字符）")
    contextualized_text: str = Field(
        default="",
        description="上下文增强文本（截断至 300 字符）",
    )
    token_count: int | None = Field(default=None, description="分块 token 数")
    heading_path: list[str] | None = Field(default=None, description="标题路径")
    page_numbers: list[int] | None = Field(default=None, description="页码列表")


# ── Token 统计 ────────────────────────────────────────────────────────


class AnswerTokens(BaseModel):
    """LLM 生成的 token 用量统计。"""

    prompt_tokens: int = Field(description="提示词 token 数")
    completion_tokens: int = Field(description="生成回答 token 数")
    total_tokens: int = Field(description="总 token 数（prompt + completion）")


# ── 完整响应 ──────────────────────────────────────────────────────────


class SearchResponse(BaseModel):
    """语义搜索 + LLM 生成 的完整响应体。"""

    # ── 请求回显与元信息 ──
    query: str = Field(description="原始查询文本（回显）")
    query_embedding_preview: list[float] = Field(description="查询向量的前 5 维预览，便于调试")
    embedding_model: str = Field(description="嵌入模型名称")
    embedding_dimensions: int = Field(description="向量维度")
    top_k: int = Field(description="请求的 top_k 值（回显）")
    total_searched: int = Field(description="搜索的向量总数")
    searched_document_count: int = Field(description="涉及的不同文档数")
    search_time_ms: float = Field(description="搜索耗时（毫秒）", ge=0)

    # ── 搜索结果 ──
    results: list[SearchResult] = Field(
        default_factory=list, description="召回的分块列表，按余弦距离升序排列"
    )

    # ── LLM 生成 ──
    answer: str = Field(default="", description="LLM 生成的 Markdown 格式回答")
    answer_tokens: AnswerTokens | None = Field(
        default=None, description="LLM 生成的 token 统计（chat 未启用时为 None）"
    )
    chat_model: str | None = Field(
        default=None, description="生成回答的对话模型名称（chat 未启用时为 None）"
    )

    # ── 调试 / 透明度 ──
    prompt_messages: list[dict] = Field(
        default_factory=list,
        description="实际发送给 LLM 的完整 messages 数组（role + content），供前端 prompt 预览使用",
    )
    chat_config_snapshot: dict | None = Field(
        default=None,
        description="ChatConfig.snapshot() 快照（不含 api_key），记录生成配置",
    )

    # ── 降级 ──
    generation_error: str | None = Field(
        default=None,
        description=(
            "LLM 生成失败时的错误信息（优雅降级）。非空时表示 answer 为降级提示而非 LLM 生成内容"
        ),
    )
