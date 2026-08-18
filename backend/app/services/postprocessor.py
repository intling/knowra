"""改写质量后处理器 —— Postprocessor 质量评估与回溯控制。

管线位置：每条策略执行后 → ``Postprocessor.evaluate()`` → 确定性预检查
→ LLM 质量评估 → 质量合格则保留，不合格则回溯（最多 1 次）
→ 二次失败丢弃回退原始查询。

确定性预检查（零 LLM 成本）：
    - 关键词留存率检查（分词后匹配）：基于 2-gram 中文分词 + 子串包含判定，
      避免逐字 n-gram 噪声。不同意图类型使用分层阈值。
    - 长度比例检查：改写长度/原始长度 < 0.3 或 > 5.0 → 标记可疑

分层阈值（按意图类型）：
    - procedural / chitchat / ambiguous → 0.50–0.55（归一化、补全本身就是目标）
    - factual → 0.80（事实类不应大幅变形）
    - 其他意图 → 0.70（默认阈值）

质量评估降级：
    - Postprocessor LLM 调用失败（超时或 API 错误）
      → 记录警告日志，保守接受改写结果
    - 单策略 normalize 预检失败 → 质量 fallback 接受（normalize 只是清理/补全）

Usage::

    postprocessor = Postprocessor(
        chat_adapter=chat_adapter,
        prompt_loader=prompt_loader,
        audit_trail=audit_trail,
    )
    result = postprocessor.evaluate("原始查询", "改写查询", intent="procedural")
    # → {"quality_scores": QualityScores(...), "passed": True, ...}
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal

from app.core.logging import get_logger
from app.services.chat_adapter import ChatAPIError

# ── QualityScores 数据模型 ────────────────────────────────────────────────────


@dataclass
class QualityScores:
    """改写质量 5 维评分。

    Attributes:
        semantic_preservation: 语义保留度（1-5）。
        clarity_improvement: 清晰度提升（1-5）。
        information_gain: 信息增量（1-5）。
        term_accuracy: 术语准确性（1-5）。
        retrievability: 可检索性（1-5）。
        total_score: 五项总分（5-25）。
        verdict: 综合评级（excellent/good/marginal/poor）。
        issues: 发现的问题列表。
    """

    semantic_preservation: int
    clarity_improvement: int
    information_gain: int
    term_accuracy: int
    retrievability: int
    total_score: int
    verdict: Literal["excellent", "good", "marginal", "poor"]
    issues: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for name in (
            "semantic_preservation",
            "clarity_improvement",
            "information_gain",
            "term_accuracy",
            "retrievability",
        ):
            value = getattr(self, name)
            if not 1 <= value <= 5:
                raise ValueError(f"{name} must be 1-5, got {value}")


# ── Postprocessor ─────────────────────────────────────────────────────────────


# 常见中文停用词（不视为有效关键词）
_STOP_WORDS: frozenset[str] = frozenset(
    {
        "的",
        "了",
        "在",
        "是",
        "我",
        "有",
        "和",
        "就",
        "不",
        "人",
        "都",
        "一",
        "一个",
        "上",
        "也",
        "很",
        "到",
        "说",
        "要",
        "去",
        "你",
        "会",
        "着",
        "没有",
        "看",
        "好",
        "自己",
        "这",
        "他",
        "她",
        "它",
        "们",
        "那",
        "些",
        "什么",
        "怎么",
        "如何",
        "哪些",
        "哪个",
        "为什么",
        "是否",
        "可以",
        "吗",
        "呢",
        "吧",
        "啊",
        "哦",
        "嗯",
        "之",
        "与",
        "于",
        "以",
        "及",
        "或",
        "但",
        "而",
        "且",
        "则",
        "因",
        "所",
        "为",
        "被",
        "把",
        "从",
        "对",
        "向",
        "往",
        "朝",
        "当",
        "由",
        "按",
        "照",
        "据",
        "沿",
        "顺",
        "凭",
        "靠",
        "用",
        "拿",
        "将",
        "连",
        "甚至",
        "以及",
    }
)


class Postprocessor:
    """改写质量后处理器。

    组合确定性预检查与 LLM 质量评估，提供统一的 evaluate() 入口，
    由 ``QueryRewriter`` 在每条策略执行后调用。

    支持按意图类型分层阈值（procedural/chitchat/ambiguous 的改写
    允许更低留存率，因为补全、规范化本身就是策略目标）。
    """

    # ── 分层关键词留存率阈值（按意图类型）──────────────────────────────────
    # procedural / chitchat / ambiguous：归一化、补全本身就是目标，阈值较低
    # factual：事实类不应大幅变形，阈值较高
    # 其他意图（analytical / comparative / exploratory / None）：使用默认值

    _INTENT_RETENTION_THRESHOLDS: dict[str, float] = {
        "procedural": 0.50,
        "chitchat": 0.55,
        "ambiguous": 0.55,
        "factual": 0.80,
    }
    _DEFAULT_RETENTION_THRESHOLD: float = 0.70

    def __init__(
        self,
        chat_adapter: object,
        prompt_loader: object,
        audit_trail: object,
        *,
        keyword_retention_threshold: float = 0.7,
        min_total_score: float = 15.0,
        llm_timeout: float = 10.0,
        llm_max_retries: int = 1,
    ) -> None:
        """初始化 Postprocessor。

        Args:
            chat_adapter: LLM 调用适配器（用于质量评估 LLM 调用）。
            prompt_loader: Prompt 模板加载器（提供 quality_evaluation 模板）。
            audit_trail: 审计日志记录器。
            keyword_retention_threshold: 关键词留存率阈值（默认 0.7）。
                低于此值 → 确定性预检查直接丢弃，跳过 LLM 评估。
            min_total_score: 质量评估最低通过分（默认 15）。
                total_score < 此值 → 视为不合格。
            llm_timeout: 质量评估 LLM 调用超时（秒，默认 10）。
            llm_max_retries: 质量评估 LLM 调用最大重试次数（默认 1）。
        """
        self._chat_adapter = chat_adapter
        self._prompt_loader = prompt_loader
        self._audit_trail = audit_trail
        self._keyword_retention_threshold = keyword_retention_threshold
        self._min_total_score = min_total_score
        self._llm_timeout = llm_timeout
        self._llm_max_retries = llm_max_retries
        self._logger = get_logger(__name__)

    # ── 确定性预检查 ──────────────────────────────────────────────────────

    @staticmethod
    def _extract_keyword_tokens(text: str) -> list[str]:
        """从文本中提取关键词分词列表（用于 token 级留存率计算）。

        与旧版 ``_extract_keywords()``（n-gram 集合取交集）不同，
        此方法：
        - 中文部分：2-gram 滑动窗口分词（"基本"、"本操"、"操作"）
          仅保留双字词，匹配更精准
        - 拉丁字母：≥2 字符单词直接加入
        - 过滤常见停用词
        - 返回有序列表（保留在原始文本中的出现顺序）

        Args:
            text: 输入文本。

        Returns:
            关键词 token 列表（有序）。
        """
        if not text or not text.strip():
            return []

        cleaned = re.sub(
            r"[，。！？、；：''（）《》【】\s.,!?;:\"'()\[\]{}]+",
            " ",
            text.strip(),
        )

        tokens: list[str] = []

        # 拉丁字母单词（≥2 字符）
        latin_words = re.findall(r"[a-zA-Z0-9]{2,}", cleaned)
        for w in latin_words:
            if w.lower() not in _STOP_WORDS:
                tokens.append(w.lower())

        # 中文 2-gram（双字词滑动窗口）
        chinese_chars = re.findall(r"[一-鿿]+", cleaned)
        for segment in chinese_chars:
            for i in range(len(segment) - 1):
                bigram = segment[i : i + 2]
                if bigram not in _STOP_WORDS:
                    tokens.append(bigram)

        return tokens

    @staticmethod
    def _compute_keyword_retention(original_tokens: list[str], rewritten_text: str) -> float:
        """基于 token 子串包含判定计算关键词留存率。

        对原始文本的每个 token，检查是否作为子串出现在改写文本中。
        相比旧版集合交集法，子串包含能正确识别 "基本" 出现在 "基本用户操作" 中。

        Args:
            original_tokens: 原始文本的关键词 token 列表。
            rewritten_text: 改写后的文本（原始字符串，不做二次分词）。

        Returns:
            留存率（0.0–1.0）。
        """
        if not original_tokens:
            return 1.0

        retained = sum(1 for token in original_tokens if token in rewritten_text)
        return retained / len(original_tokens)

    def pre_check(self, original_query: str, rewritten_query: str, intent: str | None = None) -> dict:
        """确定性预检查（零 LLM 成本）。

        检查项：
        1. **关键词留存率** — 基于 2-gram 分词 + 子串包含判定。
           留存率低于意图对应分层阈值 → ``passed=False``，直接丢弃（跳过 LLM 评估）。
        2. **长度比例** — 改写长度 / 原始长度。
           < 0.3 或 > 5.0 → 标记可疑（但不直接丢弃，仍进入 LLM 评估）。

        Args:
            original_query: 用户原始查询文本。
            rewritten_query: 改写后的查询文本。
            intent: 查询意图类型（用于分层阈值选择）。
                    为 None 时使用默认阈值 0.70。

        Returns:
            ``{"passed": bool, "issues": list[str],
              "keyword_retention": float, "length_ratio": float}``
        """
        issues: list[str] = []
        passed = True

        # 解析分层阈值：意图匹配 → 分层阈值，否则使用实例默认值
        threshold = self._INTENT_RETENTION_THRESHOLDS.get(
            intent if intent else "", self._keyword_retention_threshold
        )

        # ── 关键词留存率检查（token 级子串包含）──
        original_tokens = self._extract_keyword_tokens(original_query)

        if original_tokens:
            keyword_retention = self._compute_keyword_retention(original_tokens, rewritten_query)

            if keyword_retention < threshold:
                passed = False
                issues.append(
                    f"关键词留存率 {keyword_retention:.2f} "
                    f"低于阈值 {threshold}（意图: {intent or 'unknown'}）"
                )
                self._logger.debug(
                    "pre_check_keyword_retention_failed",
                    original_query=original_query,
                    rewritten_query=rewritten_query,
                    keyword_retention=round(keyword_retention, 3),
                    threshold=threshold,
                    intent=intent,
                )
        else:
            keyword_retention = 1.0  # 无关键词 → 跳过检查

        # ── 长度比例检查 ──
        original_len = max(len(original_query), 1)
        length_ratio = len(rewritten_query) / original_len

        if length_ratio < 0.3:
            issues.append(f"长度比例 {length_ratio:.2f} 低于 0.3，改写过短，标记可疑")
            self._logger.debug(
                "pre_check_length_too_short",
                original_query=original_query,
                rewritten_query=rewritten_query,
                length_ratio=round(length_ratio, 3),
            )
        elif length_ratio > 5.0:
            issues.append(f"长度比例 {length_ratio:.2f} 超过 5.0，改写过长，标记可疑")
            self._logger.debug(
                "pre_check_length_too_long",
                original_query=original_query,
                rewritten_query=rewritten_query,
                length_ratio=round(length_ratio, 3),
            )

        return {
            "passed": passed,
            "issues": issues,
            "keyword_retention": keyword_retention,
            "length_ratio": length_ratio,
        }

    # ── 质量评估 ──────────────────────────────────────────────────────────

    def evaluate(self, original_query: str, rewritten_query: str, intent: str | None = None) -> dict:
        """完整质量评估管线：确定性预检查 → LLM 质量评估。

        如果确定性预检查失败（关键词留存率不足），直接返回不通过，
        跳过 LLM 评估以节省成本。

        LLM 质量评估失败时（API 错误），记录警告日志，保守接受改写。
        注意：LLM 响应解析失败（ValueError）不在此处捕获，由调用方
        （QueryRewriter）统一降级处理。

        Args:
            original_query: 用户原始查询文本。
            rewritten_query: 改写后的查询文本。
            intent: 查询意图类型（用于分层阈值选择）。

        Returns:
            ``{
                "quality_scores": QualityScores | None,
                "passed": bool,
                "pre_check_failed": bool,
                "pre_check_issues": list[str],
            }``
        """
        # Step 1: 确定性预检查
        pre_check_result = self.pre_check(original_query, rewritten_query, intent=intent)
        pre_check_issues = pre_check_result["issues"]

        # 关键词留存率严重不足 → 直接丢弃，跳过 LLM 评估
        if not pre_check_result["passed"]:
            self._audit_trail.record(
                "quality_pre_check_failed",
                original_query=original_query,
                rewritten_query=rewritten_query,
                pre_check_issues=pre_check_issues,
                keyword_retention=pre_check_result["keyword_retention"],
            )
            return {
                "quality_scores": None,
                "passed": False,
                "pre_check_failed": True,
                "pre_check_issues": pre_check_issues,
            }

        # Step 2: LLM 质量评估
        try:
            # 获取 quality_evaluation prompt 模板
            prompt_template = self._prompt_loader.load("quality_evaluation")

            # 填充占位符（模板使用 {query} 和 {rewritten} 占位符）
            prompt = prompt_template.replace("{query}", original_query)
            prompt = prompt.replace("{rewritten}", rewritten_query)

            # 调用 LLM 评估（ChatAdapter.generate 需要 messages 列表格式）
            messages = [
                {"role": "user", "content": prompt},
            ]
            llm_result = self._chat_adapter.generate(
                messages,
                request_timeout=self._llm_timeout,
                max_retries=self._llm_max_retries,
            )
            response_text = llm_result.content.strip()

            # 解析 LLM 返回的 JSON 评分
            quality_scores = self._parse_quality_response(
                response_text, original_query, rewritten_query
            )

            # 判断是否通过
            score_passed = quality_scores.total_score >= self._min_total_score

            # 合并预检查标记的问题
            all_issues = pre_check_issues + quality_scores.issues

            quality_scores_with_precheck = QualityScores(
                semantic_preservation=quality_scores.semantic_preservation,
                clarity_improvement=quality_scores.clarity_improvement,
                information_gain=quality_scores.information_gain,
                term_accuracy=quality_scores.term_accuracy,
                retrievability=quality_scores.retrievability,
                total_score=quality_scores.total_score,
                verdict=quality_scores.verdict,
                issues=all_issues,
            )

            return {
                "quality_scores": quality_scores_with_precheck,
                "passed": score_passed,
                "pre_check_failed": False,
                "pre_check_issues": pre_check_issues,
            }

        except ChatAPIError as exc:
            # ── 质量评估降级 ──
            # LLM API 调用失败（超时或 API 错误）→ 记录警告日志，保守接受改写结果
            self._logger.warning(
                "quality_evaluation_llm_failed",
                original_query=original_query,
                rewritten_query=rewritten_query,
                error=str(exc),
            )
            self._audit_trail.record(
                "quality_evaluation_llm_failed",
                original_query=original_query,
                rewritten_query=rewritten_query,
                error=str(exc),
            )
            return {
                "quality_scores": None,
                "passed": True,  # 保守接受
                "pre_check_failed": False,
                "pre_check_issues": pre_check_issues,
            }

    # ── 响应解析 ──────────────────────────────────────────────────────────

    @staticmethod
    def _parse_quality_response(
        response_text: str,
        original_query: str,
        rewritten_query: str,
    ) -> QualityScores:
        """解析 LLM 质量评估响应，提取结构化评分。

        尝试从 LLM 响应中提取 JSON 块；如果解析失败，使用启发式回退。

        Args:
            response_text: LLM 返回的原始文本。
            original_query: 原始查询（用于 fallback 日志）。
            rewritten_query: 改写查询（用于 fallback 日志）。

        Returns:
            解析后的 QualityScores。

        Raises:
            ValueError: 解析完全失败时抛出。
        """
        logger = get_logger(__name__)

        # 尝试提取 JSON 块（```json ... ``` 或裸 JSON）
        json_match = re.search(
            r"```(?:json)?\s*([\s\S]*?)```",
            response_text,
        )
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            # 尝试匹配裸 JSON 对象（非贪婪，匹配第一个完整 JSON 对象）
            json_match = re.search(r"\{[^{}]*\}", response_text)
            if json_match:
                json_str = json_match.group(0).strip()
            else:
                raise ValueError(f"Cannot parse quality evaluation response: {response_text[:200]}")

        try:
            data = json.loads(json_str)

            # 提取各维度评分，缺少时使用默认值
            semantic = int(data.get("semantic_preservation", 3))
            clarity = int(data.get("clarity_improvement", 3))
            info_gain = int(data.get("information_gain", 3))
            term_acc = int(data.get("term_accuracy", 3))
            retrievability = int(data.get("retrievability", 3))

            # 计算总分
            total = int(
                data.get("total_score", semantic + clarity + info_gain + term_acc + retrievability)
            )

            # 解析 verdict
            verdict_raw = str(data.get("verdict", "marginal")).lower().strip()
            valid_verdicts = {"excellent", "good", "marginal", "poor"}
            if verdict_raw not in valid_verdicts:
                verdict_raw = "marginal"

            # 提取 issues
            issues_list = data.get("issues", [])
            issues: list[str] = (
                [str(i) for i in issues_list] if isinstance(issues_list, list) else []
            )

            return QualityScores(
                semantic_preservation=semantic,
                clarity_improvement=clarity,
                information_gain=info_gain,
                term_accuracy=term_acc,
                retrievability=retrievability,
                total_score=total,
                verdict=verdict_raw,  # type: ignore[arg-type]
                issues=issues,
            )

        except (ValueError, KeyError, TypeError) as exc:
            logger.warning(
                "quality_response_parse_failed",
                original_query=original_query,
                rewritten_query=rewritten_query,
                response_text=response_text[:500],
                error=str(exc),
            )
            raise ValueError(f"Failed to parse quality evaluation response: {exc}") from exc
