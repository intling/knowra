"""ContextVerifier —— L2 缓存上下文相关性校验器。

在 L2 语义缓存命中后，调用轻量 LLM 判断缓存的查询/答案是否依赖
当前对话历史上下文。仅当判定为"不依赖上下文"时才返回缓存结果，
否则回退到正常重写管线。

这是 L2 跨会话缓存的安全防线：
- general_knowledge 类型的缓存：仍需经过校验，防止将依赖前文的答案
  错误复用于新会话
- context_dependent 类型的缓存（同会话）：同样需要校验，确保当前
  对话上下文与缓存时一致

Usage::

    from app.services.chat_adapter import ChatAdapter
    from app.services.prompt_loader import PromptLoader

    verifier = ContextVerifier(
        chat_adapter=chat_adapter,
        prompt_loader=PromptLoader(),
    )
    result = await verifier.verify("如何优化数据库性能", history=[...])
    # → {"context_dependent": False, "reasoning": "..."}
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.services.chat_adapter import ChatAdapter, ChatAPIError
from app.services.prompt_loader import PromptLoader

# ── 代码默认提示词（YAML Catalog 不可用时的降级兜底） ──────────────────────

_DEFAULT_VERIFICATION_TEMPLATE = """\
你是一个上下文相关性判断助手。请判断以下查询的答案是否依赖于**当前对话历史**。

## 判断标准
- **依赖上下文**（context_dependent: true）：查询中包含指代词（"刚才"、"前面提到"、"那个"等）、\
省略了前文才有的主题、或答案必须结合对话历史才能给出
- **不依赖上下文**（context_dependent: false）：查询是独立的、自包含的通用问题，\
任何人都可以在没有对话历史的情况下理解和回答

## 当前对话历史
{history}

## 待判断的查询
{query}

## 输出格式
请严格输出以下 JSON 格式，不要添加任何额外内容：
{{"context_dependent": <true 或 false>, "reasoning": "<一句话说明判断依据>"}}
"""


class ContextVerifier:
    """轻量级上下文相关性校验器。

    在 L2 语义缓存命中后，调用 LLM 判断缓存查询的答案是否依赖
    当前对话历史上下文。校验不通过时管线回退到正常重写流程，
    LLM 调用失败时保守接受缓存结果（不阻断管线）。
    """

    def __init__(
        self,
        chat_adapter: ChatAdapter,
        prompt_loader: PromptLoader,
    ) -> None:
        """初始化 ContextVerifier。

        Args:
            chat_adapter: 用于调用轻量 LLM 的对话适配器。
            prompt_loader: 三层降级提示词加载器，通过
                           ``load("context_verification")`` 获取模板。
        """
        self._chat_adapter = chat_adapter
        self._prompt_loader = prompt_loader
        self._logger = get_logger(__name__)

    # ── 公共 API ──────────────────────────────────────────────────────────

    async def verify(
        self,
        query: str,
        history: list[dict] | None = None,
    ) -> dict:
        """判断 *query* 的答案是否依赖当前对话历史上下文。

        通过轻量 LLM 单轮判断，输入查询文本和对话历史摘要，
        输出 ``context_dependent`` 布尔值和推理依据。

        Args:
            query: 待判断的查询文本（来自 L2 缓存的原始查询）。
            history: 当前对话历史消息列表。为 ``None`` 或空列表时
                     直接判定为不依赖上下文（无历史可依赖）。

        Returns:
            ``dict``，包含以下键：
            - ``context_dependent``: ``True`` 表示答案依赖当前上下文，
              不应复用缓存；``False`` 表示可安全复用
            - ``reasoning``: 判断依据的一句话说明
        """
        # ── 快速路径：无对话历史时无需校验 ──
        if not history:
            return {
                "context_dependent": False,
                "reasoning": "No conversation history provided, answer is standalone.",
            }

        # ── 格式化历史 ──
        history_text = self._format_history(history)

        # ── 获取模板 ──
        template = self._prompt_loader.load("context_verification")
        user_content = template.replace("{query}", query).replace("{history}", history_text)

        messages = [
            {"role": "user", "content": user_content},
        ]

        try:
            result = self._chat_adapter.generate(messages)
            content = result.content.strip()

            parsed = self._parse_verification_response(content)
            if parsed is not None:
                self._logger.debug(
                    "context_verification_complete",
                    query=query,
                    context_dependent=parsed["context_dependent"],
                )
                return parsed

            # 解析失败 → 保守拒绝（回退到正常管线）
            self._logger.warning(
                "context_verification_parse_failed",
                query=query,
                raw_response=content[:200],
            )
            return {
                "context_dependent": True,
                "reasoning": "Failed to parse LLM verification response, "
                "conservatively rejecting cache.",
            }

        except ChatAPIError as exc:
            # LLM 调用失败 → 让管线层决定（管线层捕获此异常后
            # 保守接受缓存结果，不阻断管线）
            self._logger.warning(
                "context_verification_llm_failed",
                query=query,
                error=str(exc),
            )
            raise

    # ── 内部 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _format_history(history: list[dict]) -> str:
        """将对话历史消息列表格式化为可读文本。

        仅保留 ``user`` 和 ``assistant`` 角色，每条消息截断至
        500 字符以控制 prompt 长度（校验只需概览，不需完整历史）。
        """
        lines: list[str] = []
        for msg in history:
            role = msg.get("role", "unknown")
            if role not in ("user", "assistant"):
                continue
            content = str(msg.get("content", ""))
            if len(content) > 500:
                content = content[:500] + "..."
            role_label = {"user": "用户", "assistant": "助手"}.get(role, role)
            lines.append(f"{role_label}：{content}")
        return "\n".join(lines) if lines else "（无对话历史）"

    @staticmethod
    def _parse_verification_response(content: str) -> dict | None:
        """从 LLM 响应中解析上下文相关性判断 JSON。

        支持多种格式：纯 JSON、Markdown 代码块、含额外文本的 JSON。

        Returns:
            解析成功的 ``{"context_dependent": bool, "reasoning": str}``，
            解析失败返回 ``None``。
        """
        import json
        import re

        # 尝试 1: 直接解析
        try:
            data = json.loads(content)
            if "context_dependent" in data:
                return {
                    "context_dependent": bool(data["context_dependent"]),
                    "reasoning": str(data.get("reasoning", "")),
                }
        except json.JSONDecodeError, ValueError:
            pass

        # 尝试 2: 提取 Markdown 代码块中的 JSON
        code_block_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
        if code_block_match:
            try:
                data = json.loads(code_block_match.group(1).strip())
                if "context_dependent" in data:
                    return {
                        "context_dependent": bool(data["context_dependent"]),
                        "reasoning": str(data.get("reasoning", "")),
                    }
            except json.JSONDecodeError, ValueError:
                pass

        # 尝试 3: 提取第一个 JSON 对象
        json_match = re.search(r"\{[^{}]*\}", content)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                if "context_dependent" in data:
                    return {
                        "context_dependent": bool(data["context_dependent"]),
                        "reasoning": str(data.get("reasoning", "")),
                    }
            except json.JSONDecodeError, ValueError:
                pass

        return None
