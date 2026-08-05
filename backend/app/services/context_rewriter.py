"""基于 LLM 的对话上下文融合查询改写。

将对话历史提供给 LLM，与受保护查询一起消解不完全指代
（如 "它怎么用" → "Python 怎么使用"）。

提示词默认从 ``backend/prompts/context_fusion.yaml`` 加载，
可通过构造函数参数覆盖（便于测试和 A/B 实验）。
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.services.chat_adapter import ChatAdapter


def _format_history(history: list[dict]) -> str:
    """将对话历史消息列表格式化为可读文本。"""
    lines: list[str] = []
    for msg in history:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        role_label = {"user": "用户", "assistant": "助手", "system": "系统"}.get(role, role)
        lines.append(f"{role_label}：{content}")
    return "\n".join(lines)


def _load_default_prompt(field: str) -> str:
    """从 context_fusion.yaml 加载默认提示词字段。

    Args:
        field: 要提取的字段名（如 ``"system_prompt"``、``"user_template"``）。

    Returns:
        提示词文本；若文件缺失或字段不存在则返回空字符串。
    """
    try:
        from app.services.prompt_loader import load_prompt

        return load_prompt("context_fusion").get(field, "")
    except Exception:
        # prompt_loader 不可用或文件缺失时静默降级
        return ""


class ContextRewriter:
    """利用 LLM 将对话历史上下文融入当前查询。

    由 ``QueryRewriter`` 在上下文融合步骤中调用，当查询包含指代词
    且存在对话历史时触发。

    提示词默认从 ``backend/prompts/context_fusion.yaml`` 加载，
    可通过 *system_prompt* / *user_template* 参数覆盖。
    """

    def __init__(
        self,
        chat_adapter: ChatAdapter,
        *,
        system_prompt: str | None = None,
        user_template: str | None = None,
    ) -> None:
        self._chat_adapter = chat_adapter
        self._system_prompt = system_prompt or _load_default_prompt("system_prompt")
        self._user_template = user_template or _load_default_prompt("user_template")
        self._logger = get_logger(__name__)

    def rewrite(
        self, query: str, history: list[dict], *, model: str | None = None
    ) -> str:
        """利用 *history* 对 *query* 进行指代词消解改写。

        Args:
            query: 受保护查询（保护词已替换为占位符）。
            history: 先前的对话消息列表（role + content）。
            model: 可选的模型覆盖。为 ``None`` 时使用配置的默认模型。

        Returns:
            改写后的自包含查询字符串。
        """
        if not history:
            return query

        history_text = _format_history(history)
        user_content = self._user_template.format(history=history_text, query=query)

        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_content},
        ]

        try:
            result = self._chat_adapter.generate(messages, model=model)
            rewritten = result.content.strip()
            if not rewritten:
                self._logger.warning("context_fusion_empty_response", query=query)
                return query
            self._logger.debug("context_fusion_complete", original=query, rewritten=rewritten)
            return rewritten
        except Exception as exc:
            self._logger.warning("context_fusion_failed", query=query, error=str(exc))
            return query
