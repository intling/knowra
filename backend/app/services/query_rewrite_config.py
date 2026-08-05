"""查询重写 API 适配器的不可变配置。

所有连接参数、模型选择与运行设置均在此集中管理，可独立于主对话配置注入
``ChatAdapter``（供 ``ContextRewriter`` 使用）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings


@dataclass(frozen=True)
class QueryRewriteConfig:
    """查询重写 LLM 适配器的不可变配置。

    独立于 ``ChatConfig``，允许重写 LLM 使用不同于主对话生成的模型、温度与超时时间。
    """

    api_base_url: str
    api_key: str
    model: str
    temperature: float
    max_tokens: int
    request_timeout: float
    max_retries: int

    @classmethod
    def from_settings(cls, settings=None) -> QueryRewriteConfig:
        """从应用 Settings 对象构建配置。

        当 *settings* 为 ``None`` 时使用缓存的全局设置。
        """
        if settings is None:
            settings = get_settings()
        return cls(
            api_base_url=settings.query_rewrite_api_base_url,
            api_key=settings.query_rewrite_api_key,
            model=settings.query_rewrite_model,
            temperature=settings.query_rewrite_temperature,
            max_tokens=settings.query_rewrite_max_tokens,
            request_timeout=settings.query_rewrite_timeout,
            max_retries=settings.query_rewrite_max_retries,
        )

    def snapshot(self) -> dict[str, Any]:
        """返回可 JSON 序列化的配置快照字典。

        不包含 ``api_key`` 等敏感字段。
        """
        return {
            "api_base_url": self.api_base_url,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "request_timeout": self.request_timeout,
            "max_retries": self.max_retries,
        }
