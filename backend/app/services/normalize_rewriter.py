"""NormalizeRewriter —— 查询规范化重述策略。

将口语化查询通过 LLM 规范化为标准书面语，包括：
- 口语转书面语（"咋整Python" → "如何学习Python"）
- 错别字修正（"布署" → "部署"）
- 冗余词去除（"嗯 那个 怎么配置" → "如何配置"）
- 省略补全（补全省略的主语、宾语）

提示词默认通过 ``PromptLoader.load("normalize")`` 从
``backend/prompts/rewrite_prompts.yaml`` 加载。
词汇表通过 ``NormalizeVocabularyLoader`` 注入模板的 ``{vocabulary}`` 占位符。

LLM 调用失败时静默降级返回原始查询，确保搜索流程不中断。

Usage::

    from app.services.chat_adapter import ChatAdapter
    from app.services.prompt_loader import PromptLoader

    rewriter = NormalizeRewriter(
        chat_adapter=chat_adapter,
        prompt_loader=PromptLoader(),
    )
    result = await rewriter.rewrite("咋整Python")
    # result == {"query": "如何学习Python", "strategy": "normalize",
    #            "duration_ms": 1234.5, "tokens": 95}
"""

from __future__ import annotations

import time
from functools import lru_cache

from app.core.logging import get_logger
from app.services.chat_adapter import ChatAdapter, ChatAPIError
from app.services.prompt_loader import PromptLoader


class NormalizeRewriter:
    """口语化查询 → 规范书面语重述。

    通过 PromptLoader 获取规范化提示词模板，注入词汇表参考文本，
    填充 ``{query}`` 和 ``{protected_terms}`` 占位符后调用 LLM
    进行口语→书面语转换、错别字修正和冗余词去除。

    LLM 调用失败或返回空内容时静默降级返回原始查询。
    """

    def __init__(
        self,
        chat_adapter: ChatAdapter,
        prompt_loader: PromptLoader,
    ) -> None:
        """初始化 NormalizeRewriter。

        Args:
            chat_adapter: 用于调用 LLM 的对话适配器。
            prompt_loader: 三层降级提示词加载器，通过
                           ``load("normalize", vocabulary=...)`` 获取模板。
        """
        self._chat_adapter = chat_adapter
        self._prompt_loader = prompt_loader
        self._logger = get_logger(__name__)

    # ── 公共 API ──────────────────────────────────────────────────────────

    async def rewrite(
        self,
        query: str,
        protected_terms: list[str] | None = None,
        *,
        request_timeout: float | None = None,
        max_retries: int | None = None,
    ) -> dict:
        """对 *query* 执行规范化重述。

        通过 ``PromptLoader.load("normalize", vocabulary=...)`` 获取模板，
        填充 ``{query}`` 和 ``{protected_terms}`` 占位符，调用 LLM
        进行口语→书面语转换。

        Args:
            query: 用户原始查询文本（可能包含口语化表达、错别字、冗余词）。
            protected_terms: 受保护的术语列表（如占位符 ``__TERM1__``），
                             在改写中必须原样保留。为 ``None`` 或空列表时
                             保护词区域显示为"（无）"。
            request_timeout: LLM 调用超时（秒）。为 ``None`` 时使用
                             ChatAdapter 配置的默认值。
            max_retries: LLM 调用最大重试次数。为 ``None`` 时使用
                         ChatAdapter 配置的默认值。

        Returns:
            ``dict``，包含以下键：
            - ``query``: 规范化后的查询文本（失败时返回原始查询）
            - ``strategy``: 固定为 ``"normalize"``
            - ``duration_ms``: 执行耗时（毫秒）
            - ``tokens``: LLM 消耗的 total_tokens（失败时为 0）
        """
        start_time = time.monotonic()

        # 加载词汇表参考文本（LRU 缓存，进程生命周期内仅解析一次 YAML）
        vocabulary = NormalizeRewriter._load_vocabulary()

        # 三层降级获取模板（PromptLoader.load 已将 {vocabulary} 替换为词汇表文本）
        template = self._prompt_loader.load("normalize", vocabulary=vocabulary)

        # 准备保护词文本
        if protected_terms:
            protected_text = "\n".join(f"- {t}" for t in protected_terms)
        else:
            protected_text = "（无）"

        # 使用 str.replace 填充占位符（避免 .format() 将词汇表文本或查询中的
        # 花括号误解析为占位符，与 PromptLoader 内部处理方式保持一致）
        user_content = template.replace("{query}", query).replace(
            "{protected_terms}", protected_text
        )

        messages = [
            {"role": "user", "content": user_content},
        ]

        try:
            result = self._chat_adapter.generate(
                messages, request_timeout=request_timeout, max_retries=max_retries
            )
            rewritten = result.content.strip()

            if not rewritten:
                self._logger.warning(
                    "normalize_empty_response",
                    query=query,
                )
                elapsed_ms = (time.monotonic() - start_time) * 1000
                return {
                    "query": query,
                    "strategy": "normalize",
                    "duration_ms": elapsed_ms,
                    "tokens": 0,
                }

            elapsed_ms = (time.monotonic() - start_time) * 1000
            self._logger.debug(
                "normalize_complete",
                original=query,
                rewritten=rewritten,
                tokens=result.total_tokens,
            )
            return {
                "query": rewritten,
                "strategy": "normalize",
                "duration_ms": elapsed_ms,
                "tokens": result.total_tokens,
            }

        except ChatAPIError as exc:
            self._logger.warning(
                "normalize_failed",
                query=query,
                error=str(exc),
            )
            elapsed_ms = (time.monotonic() - start_time) * 1000
            return {
                "query": query,
                "strategy": "normalize",
                "duration_ms": elapsed_ms,
                "tokens": 0,
            }

    # ── 内部 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _load_vocabulary() -> str:
        """加载规范化词汇表，作为 Prompt 参考文本注入模板。

        通过 ``_get_cached_vocabulary()`` 获取词汇表文本（带 LRU 缓存，
        进程生命周期内仅解析 YAML 一次）。

        Returns:
            注入 Prompt 的参考文本字符串。加载失败时返回空字符串。
        """
        return _get_cached_vocabulary()


# ═══════════════════════════════════════════════════════════════════════════════
# 模块级缓存
# ═══════════════════════════════════════════════════════════════════════════════


@lru_cache(maxsize=1)
def _get_cached_vocabulary() -> str:
    """加载并缓存规范化词汇表文本。

    通过 ``NormalizeVocabularyLoader`` 解析 YAML 并生成 Prompt 参考文本。
    结果被 LRU 缓存 —— 进程生命周期内仅加载一次。

    Returns:
        结构化 Prompt 参考文本。加载失败时返回空字符串。
    """
    try:
        from app.services.prompt_loader import NormalizeVocabularyLoader

        loader = NormalizeVocabularyLoader()
        return loader.as_prompt_text()
    except Exception:
        # 词汇表加载失败不应阻止查询规范化，静默降级
        return ""
