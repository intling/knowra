"""语义搜索 + LLM 生成 API 路由。

提供 POST /api/search 端点，接收自然语言查询，跨所有已向量化文档进行语义搜索，
并调用 LLM 生成带来源引用的 AI 回答。

错误码映射：
- 200: 正常搜索+生成
- 404: 系统中无向量化数据
- 422: 请求参数校验失败（由 Pydantic 自动处理）
- 502: 查询向量化失败（嵌入 API 不可用）
- 503: Chat 功能未配置（chat_model 为空）
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.session import get_session
from app.schemas.search import SearchRequest, SearchResponse
from app.services.audit_trail import AuditTrail
from app.services.cache_manager import CacheManager
from app.services.chat_adapter import ChatAdapter
from app.services.chat_config import ChatConfig
from app.services.context_rewriter import ContextRewriter
from app.services.context_verifier import ContextVerifier
from app.services.embedding_adapter import EmbeddingAdapter, EmbeddingAPIError
from app.services.embedding_config import EmbeddingConfig
from app.services.expand_rewriter import ExpandRewriter
from app.services.kb_fingerprint import compute_fingerprint
from app.services.normalize_rewriter import NormalizeRewriter
from app.services.prompt_loader import PromptLoader
from app.services.query_rewrite_config import QueryRewriteConfig
from app.services.query_rewriter import (
    DissatisfactionDetector,
    KnowledgeClassifier,
    QueryRewriter,
)
from app.services.search import SearchService
from app.services.strategy_router import StrategyRouter
from app.services.term_align_rewriter import TermAlignRewriter
from app.services.term_protector import TermProtector

logger = get_logger(__name__)

router = APIRouter(tags=["search"])

# ── 类型别名 ──────────────────────────────────────────────────────────

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


# ── 依赖注入 ──────────────────────────────────────────────────────────


def get_chat_config(settings: SettingsDep) -> ChatConfig:
    """从应用配置构建不可变的 ChatConfig。"""
    return ChatConfig.from_settings(settings)


def get_embedding_adapter(settings: SettingsDep) -> EmbeddingAdapter:
    """构建 EmbeddingAdapter（复用现有 EmbeddingConfig 模式）。"""
    config = EmbeddingConfig.from_settings(settings)
    return EmbeddingAdapter(config=config)


def get_chat_adapter(chat_config: Annotated[ChatConfig, Depends(get_chat_config)]) -> ChatAdapter:
    """构建 ChatAdapter，与 EmbeddingAdapter 使用独立的 OpenAI 客户端实例。"""
    return ChatAdapter(config=chat_config)


def get_query_rewrite_config(settings: SettingsDep) -> QueryRewriteConfig | None:
    """从应用配置构建 QueryRewriteConfig（重写未启用时返回 None）。"""
    if not settings.query_rewrite_enabled:
        return None
    return QueryRewriteConfig.from_settings(settings)


# ── 模块级单例 ────────────────────────────────────────────────────────────
# 由于 get_settings() 已通过 @lru_cache 保证全进程返回同一 Settings
# 实例，QueryRewriter、SearchResponseCache、AuditTrail 只需构造一次
# 即可实现 L1 缓存跨请求共享。
_query_rewriter_singleton: QueryRewriter | None = None
_query_rewriter_singleton_disabled: bool = False  # 标记是否已确认"不启用"
_search_audit_trail_singleton: AuditTrail | None = None
_search_response_cache_singleton: CacheManager | None = None
_search_response_cache_disabled: bool = False  # 标记缓存是否被禁用


def get_search_audit_trail() -> AuditTrail:
    """获取搜索管线的 AuditTrail 单例（含 audit_trail_id 生成能力）。"""
    global _search_audit_trail_singleton
    if _search_audit_trail_singleton is None:
        _search_audit_trail_singleton = AuditTrail()
    return _search_audit_trail_singleton


def get_search_response_cache(settings: SettingsDep) -> CacheManager | None:
    """获取搜索响应 L1 缓存单例（会话绑定精确匹配）。

    当 ``search_cache_enabled`` 为 False 时返回 None，
    SearchService 将跳过缓存查找与存储。
    """
    global _search_response_cache_singleton, _search_response_cache_disabled

    if _search_response_cache_singleton is not None:
        return _search_response_cache_singleton
    if _search_response_cache_disabled:
        return None

    if not settings.search_cache_enabled:
        _search_response_cache_disabled = True
        return None

    _search_response_cache_singleton = CacheManager(
        max_size=settings.search_cache_max_size,
        ttl_seconds=settings.search_cache_ttl_seconds,
    )
    logger.info(
        "search_response_cache_initialized",
        max_size=settings.search_cache_max_size,
        ttl_seconds=settings.search_cache_ttl_seconds,
    )
    return _search_response_cache_singleton


def get_query_rewriter(
    settings: SettingsDep,
    query_rewrite_config: Annotated[QueryRewriteConfig | None, Depends(get_query_rewrite_config)],
) -> QueryRewriter | None:
    """构建 QueryRewriter 或返回 None（未启用/未配置时）。

    装配完整的 QueryRewriter 管线组件：
        TermProtector → CacheManager → ContextRewriter → AuditTrail

    通过模块级变量实现单例模式：QueryRewriter 及其内部 CacheManager
    在首次请求时创建，后续请求复用同一实例，从而保证 L1 缓存可在
    连续请求间命中。
    当 QUERY_REWRITE_ENABLED=false 或 QueryRewriteConfig 无效时返回 None，
    搜索管线的 Step 0（查询重写）将被跳过。
    """
    global _query_rewriter_singleton, _query_rewriter_singleton_disabled

    if _query_rewriter_singleton is not None:
        return _query_rewriter_singleton
    if _query_rewriter_singleton_disabled:
        return None

    if query_rewrite_config is None:
        _query_rewriter_singleton_disabled = True
        return None

    if not query_rewrite_config.api_key:
        logger.warning("query_rewrite_disabled", reason="api_key_empty")
        _query_rewriter_singleton_disabled = True
        return None

    # ── 组装子组件 ──────────────────────────────────────────────────
    # TermProtector：从默认词汇表和内置正则规则加载
    term_protector = TermProtector.from_defaults()

    # ChatAdapter：重写 LLM 使用独立配置（可能不同于主 chat 模型）
    rewrite_chat_adapter = ChatAdapter(config=query_rewrite_config)

    # PromptLoader：三层降级加载器（加载 rewrite_prompts.yaml）
    prompt_loader = PromptLoader()

    # ── Phase 1 组件 ────────────────────────────────────────────────
    # ContextRewriter：基于对话历史进行指代词消解
    context_rewriter = ContextRewriter(chat_adapter=rewrite_chat_adapter)

    # CacheManager：L1 精确缓存 + L2 语义缓存（内存 LRU + TTL，单例跨请求共享）
    cache_manager = CacheManager(
        ttl_seconds=settings.query_rewrite_cache_ttl_seconds,
    )

    # AuditTrail：结构化审计日志
    audit_trail = AuditTrail()

    # ── Phase 2 组件 ────────────────────────────────────────────────
    # StrategyRouter：意图分类 + 策略路由
    strategy_router = StrategyRouter(
        chat_adapter=rewrite_chat_adapter,
        prompt_loader=prompt_loader,
    )

    # NormalizeRewriter：口语→书面语规范化
    normalize_rewriter = NormalizeRewriter(
        chat_adapter=rewrite_chat_adapter,
        prompt_loader=prompt_loader,
    )

    # TermAlignRewriter：口语→正式术语对齐
    term_align_rewriter = TermAlignRewriter(
        chat_adapter=rewrite_chat_adapter,
        prompt_loader=prompt_loader,
    )

    # ExpandRewriter：模糊查询→语义扩展
    expand_rewriter = ExpandRewriter(
        chat_adapter=rewrite_chat_adapter,
        prompt_loader=prompt_loader,
    )

    # DissatisfactionDetector：不满意重试检测（默认 60s 滑动窗口）
    dissatisfaction_detector = DissatisfactionDetector(window_seconds=60.0)

    # KnowledgeClassifier：通用知识/上下文依赖分类
    knowledge_classifier = KnowledgeClassifier()

    # ContextVerifier：L2 缓存上下文相关性校验
    context_verifier = ContextVerifier(
        chat_adapter=rewrite_chat_adapter,
        prompt_loader=prompt_loader,
    )

    _query_rewriter_singleton = QueryRewriter(
        exact_term_protector=term_protector,
        context_rewriter=context_rewriter,
        cache_manager=cache_manager,
        chat_adapter=rewrite_chat_adapter,
        audit_trail=audit_trail,
        enabled=True,
        pipeline_timeout=settings.query_rewrite_pipeline_timeout,
        strategy_timeout=settings.query_rewrite_strategy_timeout,
        # Phase 2 组件
        strategy_router=strategy_router,
        normalize_rewriter=normalize_rewriter,
        term_align_rewriter=term_align_rewriter,
        expand_rewriter=expand_rewriter,
        dissatisfaction_detector=dissatisfaction_detector,
        knowledge_classifier=knowledge_classifier,
        context_verifier=context_verifier,
        # 差异化 TTL 配置（统一从 Settings 读取）
        l1_general_ttl=settings.query_rewrite_cache_ttl_seconds,
        l1_context_dependent_ttl=settings.query_rewrite_context_dependent_ttl_seconds,
        l2_general_ttl=settings.query_rewrite_l2_cache_ttl_seconds,
        l2_context_dependent_ttl=settings.query_rewrite_l2_context_dependent_ttl_seconds,
    )
    return _query_rewriter_singleton


ChatConfigDep = Annotated[ChatConfig, Depends(get_chat_config)]
EmbeddingAdapterDep = Annotated[EmbeddingAdapter, Depends(get_embedding_adapter)]
ChatAdapterDep = Annotated[ChatAdapter, Depends(get_chat_adapter)]
QueryRewriterDep = Annotated[QueryRewriter | None, Depends(get_query_rewriter)]
SearchResponseCacheDep = Annotated[CacheManager | None, Depends(get_search_response_cache)]
SearchAuditTrailDep = Annotated[AuditTrail, Depends(get_search_audit_trail)]


# ── POST /api/search ──────────────────────────────────────────────────


@router.post(
    "/search",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
)
def search_documents(
    request: SearchRequest,
    session: SessionDep,
    settings: SettingsDep,
    chat_config: ChatConfigDep,
    embedding_adapter: EmbeddingAdapterDep,
    chat_adapter: ChatAdapterDep,
    query_rewriter: QueryRewriterDep = None,
    response_cache: SearchResponseCacheDep = None,
    search_audit_trail: SearchAuditTrailDep = None,
) -> SearchResponse:
    """跨所有已向量化文档进行语义搜索，并生成 AI 回答。

    请求体：
    - **query**: 自然语言查询文本（1–2000 字符）
    - **top_k**: 返回的最相似分块数量（1–50，默认 5）
    - **history**: 可选的多轮对话历史，用于查询重写时的指代词消解

    响应体包含检索结果列表、LLM 生成的 Markdown 回答、
    Token 用量统计以及完整的 prompt messages（供调试使用）。

    - **404**: 系统中无任何已向量化文档
    - **502**: 查询向量化失败（嵌入 API 不可用）
    - **503**: Chat 功能未配置（chat_model 为空）
    """
    # 503: Chat 功能未配置 → 整个端点不可用
    if not chat_config.model:
        logger.info("search_rejected", reason="chat_disabled")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI 回答生成功能未启用，请联系管理员配置对话模型。",
        )

    # 503: Chat API key 未配置
    if not chat_config.api_key:
        logger.info("search_rejected", reason="chat_api_key_empty")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="对话 API Key 未配置，请在 .env 中设置 CHAT_API_KEY。",
        )

    service = SearchService(
        session=session,
        embedding_adapter=embedding_adapter,
        chat_adapter=chat_adapter,
        chat_config=chat_config,
        similarity_threshold=settings.search_similarity_threshold,
        min_score_threshold=settings.search_min_score_threshold,
        query_rewriter=query_rewriter,
        response_cache=response_cache,
        audit_trail=search_audit_trail,
    )

    # ── 知识库指纹注入 ──────────────────────────────────────────────────
    # 每次请求前计算当前知识库指纹，注入到查询重写缓存和搜索响应缓存中。
    # 指纹变化时，缓存层会在读取条目时惰性淘汰旧数据。
    # 指纹计算为轻量聚合查询（COUNT + MAX），通常在 1ms 内完成。
    _kb_fp = compute_fingerprint(session)
    if query_rewriter is not None:
        query_rewriter.update_fingerprint(_kb_fp)
    if response_cache is not None:
        response_cache.update_fingerprint(_kb_fp)

    try:
        response = service.search(
            query=request.query,
            top_k=request.top_k,
            history=request.history,
            session_id=request.session_id,
        )
    except EmbeddingAPIError as exc:
        logger.warning("search_embedding_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to embed query",
        ) from exc

    # 404: 系统中无向量化数据
    if response.total_searched == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="知识库中暂无任何已向量化的文档。请先上传文档并完成向量化后再提问。",
        )

    return response
