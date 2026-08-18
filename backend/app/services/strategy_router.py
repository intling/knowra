"""StrategyRouter —— 查询意图分类与策略路由决策。

采用 **启发式先行 + LLM 兜底** 两级架构：
    1. 关键词启发式分类器（<1ms）先行判定
    2. 高置信度匹配 → 直接返回，零 LLM 调用
    3. 低/中置信度 → 调用 LLM 精分类（5s 超时，不重试）
    4. LLM 失败 → 降级至启发式结果

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
# 意图分类是超轻量任务（输出 ~20 tokens JSON），正常应在 1-3 秒内完成。
# 启发式先行后，LLM 仅对低置信度查询调用，设为 5 秒严格兜底。
_DEFAULT_LLM_TIMEOUT = 5.0

# ── 默认 LLM 最大重试次数 ──────────────────────────────────────────────────
# 意图分类失败时允许 1 次重试（应对偶发网络抖动），仍失败则降级至关键词分类器。
_DEFAULT_LLM_MAX_RETRIES = 1


class StrategyRouter:
    """查询意图分类器 + 策略路由决策器。

    两级架构：
        1. 关键词启发式分类器（<1ms）先行 —— 对明确查询直接返回
        2. LLM 精分类兜底 —— 仅对低置信度查询（ambiguous、泛化兜底）调用

    LLM 调用失败或解析失败时，降级至启发式分类结果，
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
    # 每条规则包含 (意图, 复杂度, 正则列表, 置信度)。
    # 置信度：high → 跳过 LLM 直接采用；medium/low → 尝试 LLM 优化。
    # 规则按优先级从高到低排列，第一个匹配生效。

    _HEURISTIC_RULES: tuple[tuple, ...] = (
        # (意图, 复杂度, 正则模式列表, 置信度)
        # 操作/教程类查询 → procedural, complexity 4, HIGH
        (
            "procedural",
            4,
            [
                r"怎么(?:安装|配置|部署|设置|使用|用|操作|运行|启动|创建|构建|搭建|连接|集成)",
                r"如何(?:安装|配置|部署|设置|使用|用|操作|运行|启动|创建|构建|搭建|连接|集成)",
                r"(?:安装|配置|部署|设置|操作|使用|运行|启动|创建|构建|搭建)(?:步骤|教程|指南|方法|流程|过程)",
                r"(?:详细)?(?:步骤|教程|指南).*(?:安装|配置|部署|设置)",
                r"^(?:怎么|如何|怎样)(?:安装|配置|部署|设置|使用|用|操作|运行|启动|创建|搭建)",
                r"一步一步",
                r"step.?by.?step",
            ],
            "high",
        ),
        # 比较类查询 → comparative, complexity 5, HIGH
        (
            "comparative",
            5,
            [
                r"(?:对比|比较|区别|差异|不同|优劣|优缺点).*(?:和|与|vs|VS|比|还是|或者)",
                r"(?:哪个|哪种).*(?:更好|更优|更适合|更合适|更快|更强)",
                r"(?:和|与|vs|VS).*(?:对比|比较|区别|差异|哪个好)",
                r"(?:选择|选用|挑选).*(?:还是|或者)",
                r"有(?:什么|哪些)(?:区别|不同|差异)",  # "有什么区别" / "有哪些不同"
                r"(?:区别|不同|差异).*是什么",  # "...的区别是什么"
            ],
            "high",
        ),
        # 分析类查询 → analytical, complexity 5, HIGH
        (
            "analytical",
            5,
            [
                r"(?:分析|评估|评价|剖析|解读|理解).*(?:原因|原理|机制|架构|设计|影响|效果|性能)",
                r"为什么",
                r"(?:原因|原理|机制).*是什么",
                r"深度(?:分析|解读|理解)",
            ],
            "high",
        ),
        # 探索类查询 → exploratory, complexity 4, HIGH
        (
            "exploratory",
            4,
            [
                r"(?:有哪些|有什么|什么是|推荐|介绍).*(?:方案|工具|框架|方法|技术|组件|插件|库|系统|软件|操作|功能|特性|特点|优缺点|优势|劣势|类型|种类|分类|数据类型|版本|命令|语句|语法|指令)",
                r"(?:最新|前沿|趋势|发展).*(?:技术|方案|工具|框架|方法)",
                r"(?:概述|概览|总览|综述|汇总)",
                # "TOPIC有哪些/有什么" 模式（疑问词在句末的探索型查询）
                r".{3,}(?:有哪些|有什么)\s*$",
                # 泛化"介绍一下/推荐"类探索型查询
                r"(?:介绍|推荐|列举|说说|讲讲).{2,}",
            ],
            "high",
        ),
        # 简单事实查询 → factual, complexity 2, HIGH
        (
            "factual",
            2,
            [
                r"^(?:什么是|什么叫|是谁|哪个是|哪一个是).{1,30}$",
                r"^(?:定义|解释|说明).{1,30}$",
                r"(?:是什么|是谁|是哪个)",
            ],
            "high",
        ),
        # 闲聊 → chitchat, complexity 1, HIGH
        # 必须放在 ambiguous 之前，否则 "你好" 等短问候会被 ^.{1,5}$ 捕获
        (
            "chitchat",
            1,
            [
                r"^(?:你好|嗨|hello|hi|谢谢|感谢|再见|拜拜|bye).{0,5}$",
                r"^(?:你是谁|你叫什么|你能做什么|你有什么功能)",
            ],
            "high",
        ),
        # 模糊/简短查询 → ambiguous, complexity 3, MEDIUM
        # 置信度中：简短查询可能蕴含复杂意图，LLM 或许能更好地消歧
        (
            "ambiguous",
            3,
            [
                r"^.{1,5}$",  # ≤5 个字符的极短查询
                r"^(?:这个|那个|帮我|看看|查查|搜一下|搜搜|找一下)",
            ],
            "medium",
        ),
        # 兜底：含有疑问词的查询 → procedural, LOW 置信度
        # 模式泛化性强（仅匹配"怎么/如何/怎样"），LLM 精分类收益大
        ("procedural", 4, [r"(?:怎么|如何|怎样)"], "low"),
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
            llm_timeout: LLM 调用超时（秒）。启发式先行后仅低置信度查询
                         走 LLM，5 秒已足够。
            llm_max_retries: LLM 调用最大重试次数。默认 1（允许 1 次重试），
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

        启发式先行：先用关键词分类器（<1ms）判定，高置信度直接返回，
        低/中置信度时调用 LLM 精分类，LLM 失败则降级至启发式结果。

        Args:
            query: 用户查询文本（可能已经过上下文融合或保护词注入）。

        Returns:
            ``dict``，包含以下键：
            - ``intent``: 意图类型（factual/analytical/comparative/
              procedural/exploratory/chitchat/ambiguous）
            - ``complexity``: 复杂度评分（1-10 的整数）
            - ``strategies``: 应执行的策略名称列表（空列表 = direct）
            - ``source``: 分类来源（"heuristic" 或 "llm"）
        """
        start_time = time.monotonic()

        # ── 第 1 层：关键词启发式分类（<1ms，零成本）──
        intent, complexity, confidence = self._heuristic_classify(query)

        # 高置信度 → 直接采用，跳过 LLM
        if confidence == "high":
            strategies = self._decide_strategies(intent, complexity)
            elapsed_ms = (time.monotonic() - start_time) * 1000
            self._logger.debug(
                "strategy_route_heuristic_direct",
                query=query,
                intent=intent,
                complexity=complexity,
                strategies=strategies,
                confidence=confidence,
                duration_ms=elapsed_ms,
                source="heuristic",
            )
            return {
                "intent": intent,
                "complexity": complexity,
                "strategies": strategies,
                "source": "heuristic",
            }

        # ── 第 2 层：LLM 精分类（仅对低/中置信度查询）──
        llm_intent, llm_complexity = self._classify_with_llm(query)

        if llm_intent is not None and llm_complexity is not None:
            strategies = self._decide_strategies(llm_intent, llm_complexity)
            elapsed_ms = (time.monotonic() - start_time) * 1000
            self._logger.debug(
                "strategy_route_complete",
                query=query,
                intent=llm_intent,
                complexity=llm_complexity,
                strategies=strategies,
                duration_ms=elapsed_ms,
                source="llm",
            )
            return {
                "intent": llm_intent,
                "complexity": llm_complexity,
                "strategies": strategies,
                "source": "llm",
            }

        # ── 第 3 层：LLM 失败 → 降级至启发式结果 ──
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

    def _heuristic_classify(self, query: str) -> tuple[str, int, str]:
        """基于关键词模式的轻量级意图分类（<1ms，零 LLM 成本）。

        按预定义规则顺序匹配，第一个命中的规则生效。
        所有规则均未命中时返回 ``("procedural", 3, "low")`` 作为安全兜底。

        Args:
            query: 用户查询文本。

        Returns:
            ``(intent, complexity, confidence)`` 三元组。
            confidence 为 "high"、"medium" 或 "low"。
        """
        query_normalized = query.strip()

        for intent, complexity, patterns, confidence in self._HEURISTIC_RULES:
            for pattern in patterns:
                if re.search(pattern, query_normalized):
                    return intent, complexity, confidence

        # 安全兜底：低置信度，触发 LLM 精分类
        return "procedural", 3, "low"

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
        except json.JSONDecodeError, ValueError:
            pass

        # 尝试 2: 提取 Markdown 代码块中的 JSON
        code_block_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
        if code_block_match:
            try:
                data = json.loads(code_block_match.group(1).strip())
                if "intent" in data and "complexity" in data:
                    return _validate_parsed(data)
            except json.JSONDecodeError, ValueError:
                pass

        # 尝试 3: 提取第一个 JSON 对象
        json_match = re.search(r"\{[^{}]*\}", content)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                if "intent" in data and "complexity" in data:
                    return _validate_parsed(data)
            except json.JSONDecodeError, ValueError:
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
    except ValueError, TypeError:
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
