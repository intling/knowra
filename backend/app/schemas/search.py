"""搜索相关的 Pydantic Schema —— 请求、单条结果、回答 Token 统计与完整响应。"""

from uuid import UUID

from pydantic import BaseModel, Field

# ── 查询重写信息 ────────────────────────────────────────────────────────


class RewrittenQuery(BaseModel):
    """单条重写结果 —— 改写后的查询文本及其策略来源。"""

    query: str = Field(description="改写后的查询文本")
    strategy: str | None = Field(
        default=None, description="重写策略名称（如 normalize、expand 等）"
    )


class RewriteInfo(BaseModel):
    """查询重写的完整元信息 —— 原始查询、改写结果列表、使用策略、耗时与缓存命中。"""

    original_query: str = Field(description="原始查询文本")
    rewritten_queries: list[RewrittenQuery] = Field(
        default_factory=list, description="改写后的查询列表，含策略标签"
    )
    strategies_used: list[str] = Field(
        default_factory=list, description="本次重写实际使用的策略名称列表"
    )
    rewrite_time_ms: float = Field(description="重写耗时（毫秒）", ge=0)
    cache_hit: bool = Field(description="是否命中缓存")
    error: str | None = Field(
        default=None,
        description="重写失败时的错误信息，成功时为 None。非 None 时表示改写未生效，"
        "搜索使用原始查询完成，rewritten_queries 和 strategies_used 为空。",
    )
    rewrite_model: str | None = Field(
        default=None,
        description="实际使用的重写模型名称。为 None 时使用服务端默认配置。",
    )


# ── 请求 ──────────────────────────────────────────────────────────────


class SearchRequest(BaseModel):
    """语义搜索请求体。

    约束（与 spec 一致）：
    - query：1–2000 字符
    - top_k：1–50，默认 5
    - history：可选的多轮对话历史，用于指代词消解，最多保留最近 20 轮
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
    history: list[dict] | None = Field(
        default=None,
        description="可选的多轮对话历史（role + content 消息列表），用于查询重写时的指代词消解",
        max_length=20,
    )
    session_id: str | None = Field(
        default=None,
        description="可选的会话标识符，用于 L1 缓存绑定（会话级精确匹配）。"
        "为 None 时从 history 自动派生。",
        max_length=128,
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

    # ── 查询重写信息 ──
    rewrite_info: RewriteInfo = Field(
        default_factory=lambda: RewriteInfo(
            original_query="",
            rewritten_queries=[],
            strategies_used=[],
            rewrite_time_ms=0.0,
            cache_hit=False,
        ),
        description="查询重写元信息（始终返回，即使未启用重写）",
    )

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

    # ── 审计追踪 ──
    audit_trail_id: str | None = Field(
        default=None,
        description="端到端审计追踪 ID（16 字符十六进制），贯穿缓存、重写、搜索全管线，"
        "用于在日志系统中关联单个搜索请求的完整生命周期。",
    )

    # ── 降级 ──
    generation_error: str | None = Field(
        default=None,
        description=(
            "LLM 生成失败时的错误信息（优雅降级）。非空时表示 answer 为降级提示而非 LLM 生成内容"
        ),
    )
