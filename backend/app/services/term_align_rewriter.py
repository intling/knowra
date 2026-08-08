"""TermAlignRewriter —— 查询术语对齐策略。

将查询中的口语化、非正式表达替换为正式专业术语，确保改写后的查询
用词与知识库文档中的正式术语一致。

通过 PromptLoader 获取术语对齐提示词模板，注入术语对齐表参考文本，
识别查询中的口语化表达并替换为对应正式术语。

LLM 调用失败时静默降级返回原始查询，确保搜索流程不中断。

Usage::

    from app.services.chat_adapter import ChatAdapter
    from app.services.prompt_loader import PromptLoader

    rewriter = TermAlignRewriter(
        chat_adapter=chat_adapter,
        prompt_loader=PromptLoader(),
    )
    result = await rewriter.rewrite("怎么跑程序")
    # result == {"query": "如何运行程序", "strategy": "term_align",
    #            "duration_ms": 1234.5, "tokens": 95}
"""

from __future__ import annotations

import time

from app.core.logging import get_logger
from app.services.chat_adapter import ChatAdapter, ChatAPIError
from app.services.prompt_loader import PromptLoader, _load_term_alignment_vocabulary


class TermAlignRewriter:
    """口语化表达 → 正式专业术语对齐。

    通过 PromptLoader 获取术语对齐提示词模板，注入术语对齐表参考文本，
    填充 ``{query}`` 和 ``{protected_terms}`` 占位符后调用 LLM
    将查询中的口语化/非正式表达替换为正式专业术语。

    LLM 调用失败或返回空内容时静默降级返回原始查询。
    """

    def __init__(
        self,
        chat_adapter: ChatAdapter,
        prompt_loader: PromptLoader,
    ) -> None:
        """初始化 TermAlignRewriter。

        Args:
            chat_adapter: 用于调用 LLM 的对话适配器。
            prompt_loader: 三层降级提示词加载器，通过
                           ``load("term_align", vocabulary=...)`` 获取模板。
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
        """对 *query* 执行术语对齐。

        通过 ``PromptLoader.load("term_align", vocabulary=...)`` 获取模板，
        填充 ``{query}`` 和 ``{protected_terms}`` 占位符，调用 LLM
        将口语化表达替换为正式专业术语。

        Args:
            query: 用户查询文本（可能已经过规范化处理）。
            protected_terms: 受保护的术语列表（如占位符 ``__TERM1__``），
                             在术语对齐中必须原样保留。为 ``None`` 或空列表时
                             保护词区域显示为"（无）"。
            request_timeout: LLM 调用超时（秒）。为 ``None`` 时使用
                             ChatAdapter 配置的默认值。
            max_retries: LLM 调用最大重试次数。为 ``None`` 时使用
                         ChatAdapter 配置的默认值。

        Returns:
            ``dict``，包含以下键：
            - ``query``: 术语对齐后的查询文本（失败时返回原始查询）
            - ``strategy``: 固定为 ``"term_align"``
            - ``duration_ms``: 执行耗时（毫秒）
            - ``tokens``: LLM 消耗的 total_tokens（失败时为 0）
        """
        start_time = time.monotonic()

        # 加载术语对齐表参考文本
        vocabulary = _load_term_alignment_vocabulary()

        # 三层降级获取模板
        template = self._prompt_loader.load("term_align", vocabulary=vocabulary)

        # 准备保护词文本
        if protected_terms:
            protected_text = "\n".join(f"- {t}" for t in protected_terms)
        else:
            protected_text = "（无）"

        # 使用 str.replace 填充占位符
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
                    "term_align_empty_response",
                    query=query,
                )
                elapsed_ms = (time.monotonic() - start_time) * 1000
                return {
                    "query": query,
                    "strategy": "term_align",
                    "duration_ms": elapsed_ms,
                    "tokens": 0,
                }

            elapsed_ms = (time.monotonic() - start_time) * 1000
            self._logger.debug(
                "term_align_complete",
                original=query,
                rewritten=rewritten,
                tokens=result.total_tokens,
            )
            return {
                "query": rewritten,
                "strategy": "term_align",
                "duration_ms": elapsed_ms,
                "tokens": result.total_tokens,
            }

        except ChatAPIError as exc:
            self._logger.warning(
                "term_align_failed",
                query=query,
                error=str(exc),
            )
            elapsed_ms = (time.monotonic() - start_time) * 1000
            return {
                "query": query,
                "strategy": "term_align",
                "duration_ms": elapsed_ms,
                "tokens": 0,
            }
