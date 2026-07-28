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
from app.services.chat_adapter import ChatAdapter
from app.services.chat_config import ChatConfig
from app.services.embedding_adapter import EmbeddingAdapter, EmbeddingAPIError
from app.services.embedding_config import EmbeddingConfig
from app.services.search import SearchService

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


ChatConfigDep = Annotated[ChatConfig, Depends(get_chat_config)]
EmbeddingAdapterDep = Annotated[EmbeddingAdapter, Depends(get_embedding_adapter)]
ChatAdapterDep = Annotated[ChatAdapter, Depends(get_chat_adapter)]


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
) -> SearchResponse:
    """跨所有已向量化文档进行语义搜索，并生成 AI 回答。

    请求体：
    - **query**: 自然语言查询文本（1–2000 字符）
    - **top_k**: 返回的最相似分块数量（1–50，默认 5）

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
    )

    try:
        response = service.search(query=request.query, top_k=request.top_k)
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
