"""StrategyRouter —— 查询意图分类与策略路由决策。

通过 LLM 对用户查询进行意图分类和复杂度评分，根据分类结果决定
执行哪些重写策略。当 LLM 不可用或超时时，自动降级为轻量级
关键词启发式分类器（零延迟、零成本）。

路由规则：
    - factual / chitchat + complexity ≤ 2 → direct（跳过所有重写）
    - analytical / procedural / comparative + complexity 3–5
      → normalize + term_align
    - ambiguous → expand
    - complexity ≥ 6 → normalize + term_align + expand

Usage::

    from app.services.chat_adapter import ChatAdapter
    from app.services.prompt_loader import PromptLoader

    router = StrategyRouter(
        chat_adapter=chat_adapter,
        prompt_loader=PromptLoader(),
    )
    result = router.route("Redis 怎么配置")
    # → {"intent": "procedural", "complexity": 4, "strategies": ["normalize", "term_align"]}
"""

from __future__ import annotations

import json
import re
import time

from app.core.logging import get_logger
from app.services.chat_adapter import ChatAdapter, ChatAPIError
from app.services.prompt_loader import PromptLoader

# ── 默认 LLM 超时（秒）──────────────────────────────────────────────────────
# 意图分类是轻量任务（输出 ~20 tokens JSON），正常应在 2-5 秒内完成。
# 设为 8 秒给足余量，避免因偶发网络抖动误触发降级。
_DEFAULT_LLM_TIMEOUT = 8.0

# ── 默认 LLM 最大重试次数 ──────────────────────────────────────────────────
# 意图分类失败时允许 1 次重试（应对偶发网络抖动），仍失败则降级至关键词分类器。
_DEFAULT_LLM_MAX_RETRIES = 1


class StrategyRouter:
    """查询意图分类器 + 策略路由决策器。

    通过 PromptLoader 获取意图分类提示词模板，调用 LLM 对查询进行
    意图分类和复杂度评分，然后根据规则决定执行哪些重写策略。

    LLM 调用失败或解析失败时，优先使用关键词启发式分类器降级，
    确保管线不中断且保持合理的分类质量。
    """

    # ── 路由规则 ─────────────────────────────────────────────────────────

    # (intent_whitelist, complexity_range) → strategies
    # 注意：路由规则按声明顺序匹配，第一个匹配的规则生效。
    _ROUTE_RULES: tuple[tuple, ...] = (
        # 高复杂度（≥6）→ 全部三个策略（意图不限）
        (None, (6, 10), ["normalize", "term_align", "expand"]),
        # ambiguous 意图 → 仅 expand
        (frozenset({"ambiguous"}), (1, 10), ["expand"]),
        # 中等复杂度（3-5）+ 非闲聊/非事实 → normalize + term_align
        (
            frozenset({"analytical", "procedural", "comparative", "exploratory"}),
            (3, 5),
            ["normalize", "term_align"],
        ),
        # 低复杂度（≤2）→ direct（跳过所有策略）
        (None, (1, 2), []),
        # 兜底：任何未命中 → direct
    )

    # ── 关键词启发式分类规则 ──────────────────────────────────────────────
    # 当 LLM 不可用时，使用以下规则在 <1ms 内完成分类。
    # 规则按优先级从高到低排列，第一个匹配生效。

    _HEURISTIC_RULES: tuple[tuple, ...] = (
        # (意图, 复杂度, 正则模式列表)
        # 操作/教程类查询 → procedural, complexity 4
        (
            "procedural",
            4,
            [
                r"怎么(?:安装|配置|部署|设置|使用|操作|运行|启动|创建|构建|搭建|连接|集成)",
                r"如何(?:安装|配置|部署|设置|使用|操作|运行|启动|创建|构建|搭建|连接|集成)",
                r"(?:安装|配置|部署|设置|操作|运行|启动|创建|构建|搭建)(?:步骤|教程|指南|方法|流程|过程)",
                r"(?:详细)?(?:步骤|教程|指南).*(?:安装|配置|部署|设置)",
                r"^(?:怎么|如何|怎样)(?:安装|配置|部署|设置|使用|操作|运行|启动|创建|搭建)",
                r"一步一步",
                r"step.?by.?step",
            ],
        ),
        # 比较类查询 → comparative, complexity 5
        (
            "comparative",
            5,
            [
                r"(?:对比|比较|区别|差异|不同|优劣|优缺点).*(?:和|与|vs|VS|比|还是|或者)",
                r"(?:哪个|哪种).*(?:更好|更优|更适合|更合适|更快|更强)",
                r"(?:和|与|vs|VS).*(?:对比|比较|区别|差异|哪个好)",
                r"(?:选择|选用|挑选).*(?:还是|或者)",
            ],
        ),
        # 分析类查询 → analytical, complexity 5
        (
            "analytical",
            5,
            [
                r"(?:分析|评估|评价|剖析|解读|理解).*(?:原因|原理|机制|架构|设计|影响|效果|性能)",
                r"为什么",
                r"(?:原因|原理|机制).*是什么",
                r"深度(?:分析|解读|理解)",
            ],
        ),
        # 探索类查询 → exploratory, complexity 4
        (
            "exploratory",
            4,
            [
                r"(?:有哪些|有什么|什么是|推荐|介绍).*(?:方案|工具|框架|方法|技术|组件|插件|库|系统|软件)",
                r"(?:最新|前沿|趋势|发展).*(?:技术|方案|工具|框架|方法)",
                r"(?:概述|概览|总览|综述|汇总)",
            ],
        ),
        # 简单事实查询 → factual, complexity 2
        (
            "factual",
            2,
            [
                r"^(?:什么是|什么叫|是谁|哪个是|哪一个是).{1,30}$",
                r"^(?:定义|解释|说明).{1,30}$",
                r"(?:是什么|是谁|是哪个)",
            ],
        ),
        # 模糊/简短查询 → ambiguous, complexity 3
        (
            "ambiguous",
            3,
            [
                r"^.{1,5}$",  # ≤5 个字符的极短查询
                r"^(?:这个|那个|帮我|看看|查查|搜一下|搜搜|找一下)",
            ],
        ),
        # 闲聊 → chitchat, complexity 1
        (
            "chitchat",
            1,
            [
                r"^(?:你好|嗨|hello|hi|谢谢|感谢|再见|拜拜|bye).{0,5}$",
                r"^(?:你是谁|你叫什么|你能做什么|你有什么功能)",
            ],
        ),
        # 兜底：中等复杂度的操作类查询
        ("procedural", 4, [r"(?:怎么|如何|怎样)"]),
    )

    # ── 构造 ─────────────────────────────────────────────────────────────

    def __init__(
        self,
        chat_adapter: ChatAdapter,
        prompt_loader: PromptLoader,
        llm_timeout: float = _DEFAULT_LLM_TIMEOUT,
        llm_max_retries: int = _DEFAULT_LLM_MAX_RETRIES,
    ) -> None:
        """初始化 StrategyRouter。

        Args:
            chat_adapter: 用于调用 LLM 的对话适配器。
            prompt_loader: 三层降级提示词加载器，通过
                           ``load("intent_classification")`` 获取模板。
            llm_timeout: LLM 调用超时（秒）。意图分类是轻量任务，
                         默认 8 秒已足够。
            llm_max_retries: LLM 调用最大重试次数。默认 0（不重试），
                             失败时直接使用启发式降级。
        """
        self._chat_adapter = chat_adapter
        self._prompt_loader = prompt_loader
        self._llm_timeout = llm_timeout
        self._llm_max_retries = llm_max_retries
        self._logger = get_logger(__name__)

    # ── 公共 API ──────────────────────────────────────────────────────────

    def route(self, query: str) -> dict:
        """对 *query* 进行意图分类和策略路由。

        优先调用 LLM 进行高精度分类；LLM 不可用或超时时自动降级为
        关键词启发式分类器，确保管线零阻塞。

        Args:
            query: 用户查询文本（可能已经过上下文融合或保护词注入）。

        Returns:
            ``dict``，包含以下键：
            - ``intent``: 意图类型（factual/analytical/comparative/
              procedural/exploratory/chitchat/ambiguous）
            - ``complexity``: 复杂度评分（1-10 的整数）
            - ``strategies``: 应执行的策略名称列表（空列表 = direct）
            - ``source``: 分类来源（"llm" 或 "heuristic"）
        """
        start_time = time.monotonic()

        # ── 尝试 LLM 分类 ──
        intent, complexity = self._classify_with_llm(query)

        if intent is not None and complexity is not None:
            strategies = self._decide_strategies(intent, complexity)
            elapsed_ms = (time.monotonic() - start_time) * 1000
            self._logger.debug(
                "strategy_route_complete",
                query=query,
                intent=intent,
                complexity=complexity,
                strategies=strategies,
                duration_ms=elapsed_ms,
                source="llm",
            )
            return {
                "intent": intent,
                "complexity": complexity,
                "strategies": strategies,
                "source": "llm",
            }

        # ── LLM 失败 → 关键词启发式降级 ──
        intent, complexity = self._heuristic_classify(query)
        strategies = self._decide_strategies(intent, complexity)
        elapsed_ms = (time.monotonic() - start_time) * 1000
        self._logger.info(
            "strategy_route_heuristic_fallback",
            query=query,
            intent=intent,
            complexity=complexity,
            strategies=strategies,
            duration_ms=elapsed_ms,
        )
        return {
            "intent": intent,
            "complexity": complexity,
            "strategies": strategies,
            "source": "heuristic",
        }

    # ── LLM 分类 ─────────────────────────────────────────────────────────

    def _classify_with_llm(self, query: str) -> tuple[str | None, int | None]:
        """尝试通过 LLM 进行意图分类。

        Returns:
            ``(intent, complexity)``，失败时返回 ``(None, None)``。
        """
        template = self._prompt_loader.load("intent_classification")
        user_content = template.replace("{query}", query)
        messages = [
            {"role": "user", "content": user_content},
        ]

        try:
            result = self._chat_adapter.generate(
                messages,
                request_timeout=self._llm_timeout,
                max_retries=self._llm_max_retries,
            )
            content = result.content.strip()
            parsed = self._parse_classification_response(content)

            if parsed is None:
                self._logger.warning(
                    "strategy_router_parse_failed",
                    query=query,
                    raw_response=content[:200],
                )
                return None, None

            return parsed["intent"], parsed["complexity"]

        except ChatAPIError as exc:
            self._logger.warning(
                "strategy_router_llm_failed",
                query=query,
                error=str(exc),
            )
            return None, None

    # ── 关键词启发式分类 ─────────────────────────────────────────────────

    def _heuristic_classify(self, query: str) -> tuple[str, int]:
        """基于关键词模式的轻量级意图分类（<1ms，零 LLM 成本）。

        按预定义规则顺序匹配，第一个命中的规则生效。
        所有规则均未命中时返回 ``("factual", 3)`` 作为安全兜底。

        Args:
            query: 用户查询文本。

        Returns:
            ``(intent, complexity)`` 元组。
        """
        query_normalized = query.strip()

        for intent, complexity, patterns in self._HEURISTIC_RULES:
            for pattern in patterns:
                if re.search(pattern, query_normalized):
                    return intent, complexity

        # 安全兜底：中等复杂度的操作类查询（最常见的查询类型）
        return "procedural", 3

    # ── 内部 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_classification_response(content: str) -> dict | None:
        """从 LLM 响应中解析意图分类 JSON。

        支持多种格式：
        1. 纯 JSON：``{"intent": "factual", "complexity": 2}``
        2. Markdown 代码块包裹的 JSON
        3. 包含额外文本的 JSON（提取第一个 JSON 对象）

        Returns:
            解析成功的 ``{"intent": str, "complexity": int}``，
            解析失败返回 ``None``。
        """
        # 尝试 1: 直接解析
        try:
            data = json.loads(content)
            if "intent" in data and "complexity" in data:
                return _validate_parsed(data)
        except (json.JSONDecodeError, ValueError):
            pass

        # 尝试 2: 提取 Markdown 代码块中的 JSON
        code_block_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
        if code_block_match:
            try:
                data = json.loads(code_block_match.group(1).strip())
                if "intent" in data and "complexity" in data:
                    return _validate_parsed(data)
            except (json.JSONDecodeError, ValueError):
                pass

        # 尝试 3: 提取第一个 JSON 对象
        json_match = re.search(r"\{[^{}]*\}", content)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                if "intent" in data and "complexity" in data:
                    return _validate_parsed(data)
            except (json.JSONDecodeError, ValueError):
                pass

        return None

    def _decide_strategies(self, intent: str, complexity: int) -> list[str]:
        """根据意图和复杂度决定策略列表。

        按声明顺序匹配路由规则，第一个匹配的规则生效。
        未命中任何规则时返回空列表（direct）。

        Args:
            intent: 意图类型。
            complexity: 复杂度评分（1-10）。

        Returns:
            策略名称列表。
        """
        for intent_set, (lo, hi), strategies in self._ROUTE_RULES:
            # 复杂度范围匹配
            if not (lo <= complexity <= hi):
                continue
            # 意图匹配（None = 任意意图）
            if intent_set is not None and intent not in intent_set:
                continue
            return list(strategies)

        # 兜底：direct
        return []

    @staticmethod
    def _fallback_route() -> dict:
        """LLM 调用失败时的降级路由结果。

        返回 direct（空策略列表），确保管线不中断。

        .. deprecated::
            请使用 ``_heuristic_classify()`` 代替 —— 它提供更好的降级质量。
            保留此方法仅为向后兼容旧调用方。
        """
        return {
            "intent": None,
            "complexity": None,
            "strategies": [],
            "source": "fallback",
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 模块级辅助函数
# ═══════════════════════════════════════════════════════════════════════════════

_VALID_INTENTS: frozenset[str] = frozenset(
    {
        "factual",
        "analytical",
        "comparative",
        "procedural",
        "exploratory",
        "chitchat",
        "ambiguous",
    }
)


def _validate_parsed(data: dict) -> dict:
    """验证并修正解析后的意图分类数据。

    Args:
        data: 包含 ``intent`` 和 ``complexity`` 的字典。

    Returns:
        规范化后的 ``{"intent": str, "complexity": int}``。

    Raises:
        ValueError: 数据无效且无法修正。
    """
    intent = str(data.get("intent", "")).lower().strip()
    if intent not in _VALID_INTENTS:
        # 尝试模糊匹配常见变体
        intent = _fuzzy_match_intent(intent)

    try:
        complexity = int(data.get("complexity", 5))
    except (ValueError, TypeError):
        complexity = 5

    # 钳制范围
    complexity = max(1, min(10, complexity))

    return {"intent": intent, "complexity": complexity}


def _fuzzy_match_intent(intent: str) -> str:
    """对未识别的意图标签进行模糊匹配。

    Args:
        intent: 原始意图字符串。

    Returns:
        最接近的有效意图类型，无法匹配时返回 ``"factual"``。
    """
    # 常见变体 → 标准名称
    _ALIASES: dict[str, str] = {
        "事实": "factual",
        "事实型": "factual",
        "分析": "analytical",
        "分析型": "analytical",
        "比较": "comparative",
        "比较型": "comparative",
        "操作": "procedural",
        "操作型": "procedural",
        "过程": "procedural",
        "探索": "exploratory",
        "探索型": "exploratory",
        "闲聊": "chitchat",
        "聊天": "chitchat",
        "模糊": "ambiguous",
        "不明确": "ambiguous",
    }
    return _ALIASES.get(intent, "factual")
