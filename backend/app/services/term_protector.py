"""精确词保护模块 —— 在查询重写前后保护技术术语不被 LLM 意外替换或翻译。

识别通过正则匹配（版本号、IP 地址、全大写缩写、驼峰命名、路径/URL）和可配置的
自定义词汇表完成。保护流程为：匹配 → 占位符替换 → LLM 重写 → 占位符还原，零 LLM 成本。

三层降级加载（高 → 低）：
    1. 环境变量 ``QUERY_REWRITE_PROTECT_TERMS_CUSTOM_LIST``（逗号分隔，紧急热修复）
    2. YAML 词汇表文件 ``backend/prompts/protected_terms.yaml``（运维友好，Git 追踪）
    3. 内置正则规则（代码默认值，零配置可用）

Usage::

    protector = TermProtector.from_defaults()
    protected_query, term_map = protector.protect("如何配置 Nginx 反向代理")
    # protected_query: "如何配置 [[TERM_0]] 反向代理"
    # term_map: {0: "Nginx"}

    # ... LLM 重写 ...

    restored = protector.restore("[[TERM_0]] 反向代理 怎么配置", term_map)
    # restored: "Nginx 反向代理 怎么配置"
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import yaml

from app.core.logging import get_logger

_PLACEHOLDER_PATTERN = re.compile(r"\[\[TERM_(\d+)\]\]")

# ── 内置正则规则集 ──────────────────────────────────────────────────────────
# 每条规则为 (名称, 正则模式) 元组。
# 规则按顺序应用，先匹配的规则优先级更高。

_BUILTIN_PATTERNS: tuple[tuple[str, str], ...] = (
    # ── URL / 含协议链接 ──
    (
        "url",
        r"\bhttps?://[^\s<>\"'，。！？、；：（）【】《》\u4e00-\u9fff]+",
    ),
    # ── 文件路径（Unix / Windows）──
    (
        "file_path",
        r"(?:/(?:[\w.\-]+/)+[\w.\-]+(?:\.\w+)?)"  # /usr/local/bin/tool
        r"|"
        r"(?:[A-Za-z]:\\(?:[\w.\-]+\\)+[\w.\-]+(?:\.\w+)?)",  # C:\Program Files\app
    ),
    # ── 版本号 ──
    (
        "version",
        r"\b\d+\.\d+(?:\.\d+)*(?:-[A-Za-z0-9_.]+)?"
        r"(?:\s*\(\d{4}-\d{2}-\d{2}\))?",  # 可选发布日期后缀
    ),
    # ── IPv4 / IPv6 ──
    (
        "ip_address",
        r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
        r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
        r"|"
        r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b",
    ),
    # ── 全大写缩写（≥2 字符，排除单字母单词）──
    (
        "uppercase_acronym",
        r"\b[A-Z]{2,}(?:\d+)?\b",  # CSS, HTML5, API
    ),
    # ── 驼峰命名（含 PascalCase / dromedaryCase）──
    (
        "camel_case",
        r"\b(?:[A-Z][a-z0-9]+(?:\d+)?){2,}\b"  # ReactRouter, getUserData
        r"|"
        r"\b[a-z]+(?:[A-Z][a-z0-9]+)+\b",
    ),
    # ── 下划线命名（snake_case 标识符，≥2 段）──
    (
        "snake_case",
        r"\b[a-z]+(?:_[a-z0-9]+){1,}\b",
    ),
    # ── 邮件地址 ──
    (
        "email",
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    ),
    # ── 技术标识符（$ENV_VAR, --flag-name, @annotation）──
    (
        "technical_identifier",
        r"\$\{[A-Z_]+\}"  # ${ENV_VAR}
        r"|"
        r"\$[A-Z_][A-Z0-9_]*"  # $ENV_VAR
        r"|"
        r"--?[a-z][a-z0-9-]*(?:=[^\s]*)?"  # --flag / --flag=value
        r"|"
        r"@[a-zA-Z][\w.]*",  # @annotation
    ),
)

# ── 默认词汇表路径 ──────────────────────────────────────────────────────────

_DEFAULT_VOCAB_PATH = (
    Path(__file__).resolve().parent.parent.parent / "prompts" / "protected_terms.yaml"
)


class TermProtector:
    """精确词保护器 —— 识别并保护技术术语，防止 LLM 意外替换或翻译。

    保护流程：
        1. 词汇表匹配 → 2. 正则匹配（去重叠） →
        3. 占位符替换 → 4. LLM 重写 → 5. 占位符还原

    内置正则规则覆盖：URL、路径、版本号、IP 地址、全大写缩写、驼峰/蛇形命名、
    邮件地址、环境变量、命令行标志等。自定义词汇表通过 JSON 文件加载，匹配
    优先级高于正则规则。
    """

    def __init__(
        self,
        vocabulary: set[str] | frozenset[str] | None = None,
        extra_vocabulary: set[str] | frozenset[str] | None = None,
        patterns: tuple[tuple[str, str], ...] | None = None,
    ) -> None:
        """初始化 TermProtector。

        Args:
            vocabulary: 自定义术语集合，优先级高于内置正则匹配。
            extra_vocabulary: 额外术语，与 vocabulary 合并（不替代）。
            patterns: 自定义正则规则集。为 None 时使用内置规则。
        """
        self._logger = get_logger(__name__)

        # 合并词汇表
        vocab: set[str] = set(vocabulary or ())
        if extra_vocabulary:
            vocab.update(extra_vocabulary)
        self._vocabulary: frozenset[str] = frozenset(vocab)

        # 编译正则规则。使用 re.ASCII 确保 \b / \w 在 ASCII 术语与
        # CJK 字符相邻时正确触发词边界（如 "HDFS如何编程"）。
        # Python 默认 Unicode 模式将 CJK 字符视为 \w，导致边界失效。
        raw_patterns = patterns if patterns is not None else _BUILTIN_PATTERNS
        self._regex_rules: list[tuple[str, re.Pattern[str]]] = [
            (name, re.compile(pattern, re.ASCII)) for name, pattern in raw_patterns
        ]

        self._vocab_count = len(self._vocabulary)
        self._regex_count = len(self._regex_rules)

        if self._vocab_count > 0 or self._regex_count > 0:
            self._logger.debug(
                "term_protector_initialized",
                vocab_terms=self._vocab_count,
                regex_rules=self._regex_count,
            )
        else:
            self._logger.warning("term_protector_no_rules")

    # ── 工厂方法 ─────────────────────────────────────────────────────────

    @classmethod
    def from_defaults(
        cls,
        extra_terms: set[str] | frozenset[str] | None = None,
    ) -> TermProtector:
        """从默认词汇表文件和内置正则规则创建 TermProtector。

        三层降级加载（高 → 低）：
            1. 环境变量 ``QUERY_REWRITE_PROTECT_TERMS_CUSTOM_LIST``（逗号分隔，紧急热修复）
            2. YAML 词汇表文件 ``backend/prompts/protected_terms.yaml``
               （路径可通过 ``QUERY_REWRITE_PROTECT_TERMS_PATH`` 覆盖）
            3. 内置正则规则（代码默认值，零配置可用）

        Args:
            extra_terms: 额外保护术语，附加到默认词汇表之后（不替代）。
        """
        # Tier 1: 环境变量紧急覆盖（逗号分隔的额外术语）
        custom_list = os.environ.get("QUERY_REWRITE_PROTECT_TERMS_CUSTOM_LIST", "")
        env_terms: set[str] = set()
        if custom_list:
            env_terms = {t.strip() for t in custom_list.split(",") if t.strip()}

        # Tier 2: YAML 词汇表文件
        vocab_path = os.environ.get("QUERY_REWRITE_PROTECT_TERMS_PATH", str(_DEFAULT_VOCAB_PATH))
        vocabulary = frozenset(_load_vocabulary_from_yaml_file(vocab_path))

        # 合并各来源术语（Tier 1 追加，不替代 Tier 2）
        if env_terms:
            vocabulary = vocabulary | frozenset(env_terms)
        if extra_terms:
            vocabulary = vocabulary | frozenset(extra_terms)

        return cls(vocabulary=vocabulary)

    @classmethod
    def from_vocab_file(
        cls,
        file_path: str | Path,
        extra_terms: set[str] | frozenset[str] | None = None,
    ) -> TermProtector:
        """从指定词汇表文件创建 TermProtector。

        支持 YAML（.yaml / .yml）和 JSON（.json）格式，根据文件扩展名自动判断。

        Args:
            file_path: 词汇表文件路径（YAML 或 JSON）。
            extra_terms: 额外保护术语。

        Raises:
            FileNotFoundError: 词汇表文件不存在。
            yaml.YAMLError: YAML 格式无效。
            json.JSONDecodeError: JSON 格式无效。
        """
        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix in (".yaml", ".yml"):
            vocabulary = frozenset(_load_vocabulary_from_yaml_file(path))
        else:
            vocabulary = frozenset(_load_vocabulary_from_json_file(path))
        if extra_terms:
            vocabulary = vocabulary | frozenset(extra_terms)
        return cls(vocabulary=vocabulary)

    # ── 公共 API ─────────────────────────────────────────────────────────

    def protect(self, text: str) -> tuple[str, dict[int, str]]:
        """扫描文本中的保护词，替换为占位符。

        匹配优先级：词汇表（最高） > 正则规则。若词汇表匹配与正则匹配
        重叠，以词汇表匹配为准，丢弃冲突的正则匹配。

        Args:
            text: 原始查询文本。

        Returns:
            (protected_text, term_map) 元组：
            - protected_text: 保护词替换为 [[TERM_N]] 占位符后的文本。
            - term_map: 占位符索引 → 原始术语的映射。
        """
        if not text:
            return text, {}

        matches: list[_Match] = []

        # Step 1: 词汇表匹配（精确词边界）
        if self._vocabulary:
            matches.extend(_find_vocabulary_matches(text, self._vocabulary))

        # Step 2: 正则规则匹配
        for _name, pattern in self._regex_rules:
            for m in pattern.finditer(text):
                matches.append(_Match(start=m.start(), end=m.end(), text=m.group()))

        if not matches:
            return text, {}

        # Step 3: 去重叠 —— 词汇表匹配优先，去除与之重叠的正则匹配
        matches = _deduplicate_matches(matches)

        if not matches:
            return text, {}

        # Step 4: 按位置排序并分配占位符索引
        matches.sort(key=lambda m: m.start)

        # 相同术语复用同一占位符索引
        term_to_idx: dict[str, int] = {}
        term_map: dict[int, str] = {}
        next_idx = 0

        for match in matches:
            term = match.text
            if term not in term_to_idx:
                term_to_idx[term] = next_idx
                term_map[next_idx] = term
                next_idx += 1

        # Step 5: 从右向左替换，避免位置偏移
        result_parts: list[str] = []
        cursor = 0
        for match in sorted(matches, key=lambda m: m.start):
            idx = term_to_idx[match.text]
            result_parts.append(text[cursor : match.start])
            result_parts.append(f"[[TERM_{idx}]]")
            cursor = match.end
        result_parts.append(text[cursor:])

        protected = "".join(result_parts)

        self._logger.debug(
            "term_protection_applied",
            original_length=len(text),
            protected_length=len(protected),
            terms_protected=len(term_map),
            term_count=len(matches),
        )

        return protected, term_map

    def restore(self, text: str, term_map: dict[int, str]) -> str:
        """将占位符还原为原始术语。

        Args:
            text: 包含 [[TERM_N]] 占位符的文本。
            term_map: 占位符索引 → 原始术语的映射。

        Returns:
            还原后的文本。若 term_map 为空或文本中无占位符则原样返回。
        """
        if not term_map or not text:
            return text

        def _replacer(m: re.Match[str]) -> str:
            idx = int(m.group(1))
            return term_map.get(idx, m.group(0))

        restored = _PLACEHOLDER_PATTERN.sub(_replacer, text)

        if restored != text:
            self._logger.debug(
                "term_restoration_applied",
                placeholders_restored=len(_PLACEHOLDER_PATTERN.findall(text)),
            )

        return restored

    # ── 属性 ─────────────────────────────────────────────────────────────

    @property
    def vocabulary_size(self) -> int:
        """当前加载的词汇表词条数。"""
        return self._vocab_count

    @property
    def regex_rule_count(self) -> int:
        """已编译的正则规则数量。"""
        return self._regex_count


# ═══════════════════════════════════════════════════════════════════════════
# 内部辅助
# ═══════════════════════════════════════════════════════════════════════════


class _Match:
    """一次匹配记录。"""

    __slots__ = ("start", "end", "text")

    def __init__(self, start: int, end: int, text: str) -> None:
        self.start = start
        self.end = end
        self.text = text

    def overlaps(self, other: _Match) -> bool:
        """判断两个匹配是否重叠（含端点相邻视为不重叠）。"""
        return self.start < other.end and other.start < self.end


def _find_vocabulary_matches(text: str, vocabulary: frozenset[str]) -> list[_Match]:
    """在文本中查找词汇表术语的所有出现位置。

    按术语长度降序排列后扫描，确保较长术语优先匹配
    （如 "Ruby on Rails" 优先于 "Ruby"）。

    对于纯 ASCII 术语使用 ``(?<!\\w)`` / ``(?!\\w)`` 词边界，
    防止 "React" 误匹配 "Reaction"。对于含 CJK 字符的术语使用
    纯子串匹配（自然语言无空格分词场景）。
    """
    matches: list[_Match] = []
    # 按长度降序 —— 长术语优先
    sorted_terms = sorted(vocabulary, key=len, reverse=True)

    for term in sorted_terms:
        escaped = re.escape(term)

        if _is_ascii_only(term):
            # ASCII 术语 —— 使用词边界防止子串误匹配。
            # 必须使用 re.ASCII：Python 默认 Unicode 模式下 CJK 字符属于 \w，
            # 导致 \b 在 "HDFS" 和 "如何" 之间不触发，词汇表中的 ASCII 术语
            # 无法在中文查询中被识别（如 "HDFS如何编程"）。
            pattern = re.compile(rf"(?<!\w){escaped}(?!\w)", re.ASCII)
        else:
            # 含非 ASCII 字符（CJK 等）—— 纯子串匹配
            # 因为 CJK 文本通常无空格分隔，词边界（\b / \w）在 CJK
            # 字符之间不生效
            pattern = re.compile(escaped)

        for m in pattern.finditer(text):
            matches.append(_Match(start=m.start(), end=m.end(), text=term))

    return matches


def _is_ascii_only(text: str) -> bool:
    """检测文本是否全由 ASCII 字符组成。"""
    return all(ord(c) < 128 for c in text)


def _deduplicate_matches(matches: list[_Match]) -> list[_Match]:
    """去除重叠的匹配，最长匹配优先。

    策略：按 start 升序、end 降序（长匹配优先）排列，跳过与已保留
    匹配重叠的新匹配。这确保了较长的短语（如 "Spring Boot"）不会被
    较短的子串（如 "Spring"）遮挡。
    """
    if len(matches) <= 1:
        return matches

    # 按起始位置升序，相同起始则按结束位置降序（长的在前）
    matches.sort(key=lambda m: (m.start, -m.end))

    kept: list[_Match] = []
    for match in matches:
        # 检查是否与已保留的匹配重叠
        if any(kept_match.overlaps(match) for kept_match in kept):
            continue
        kept.append(match)

    return kept


# ═══════════════════════════════════════════════════════════════════════════
# 词汇表加载（三层降级：环境变量 → YAML Catalog → 内置正则）
# ═══════════════════════════════════════════════════════════════════════════


def _load_vocabulary_from_yaml_file(file_path: str | Path) -> set[str]:
    """从 YAML 词汇表文件加载术语集合（Tier 2）。

    支持两种格式：
    1. 分类格式（推荐）：::

         categories:
           cat_name:
             - term1
             - term2
         flat_terms:
           - term3
           - term4

    2. 简单列表格式：::

         - term1
         - term2

    加载失败时静默降级为空集合（不影响系统运行），通过日志记录警告。

    Args:
        file_path: YAML 文件路径（支持相对路径和绝对路径）。

    Returns:
        术语集合，加载失败时返回空集合。
    """
    path = Path(file_path)
    if not path.exists():
        logger = get_logger(__name__)
        logger.warning(
            "vocab_file_not_found",
            path=str(path),
            format="yaml",
        )
        return set()

    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, OSError) as exc:
        logger = get_logger(__name__)
        logger.warning(
            "vocab_file_load_failed",
            path=str(path),
            format="yaml",
            error=str(exc),
        )
        return set()

    return _extract_terms_from_vocab_data(data)


def _load_vocabulary_from_json_file(file_path: str | Path) -> set[str]:
    """从 JSON 词汇表文件加载术语集合（向后兼容）。

    支持两种格式：
    1. 分类格式（推荐）：{"categories": {"cat_name": ["term1", ...]}, "flat_terms": ["term2", ...]}
    2. 简单列表格式：["term1", "term2", ...]

    Args:
        file_path: JSON 文件路径。

    Returns:
        术语集合。

    Raises:
        FileNotFoundError: 文件不存在。
        json.JSONDecodeError: JSON 格式无效。
    """
    path = Path(file_path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    return _extract_terms_from_vocab_data(data)


def _extract_terms_from_vocab_data(data: object) -> set[str]:
    """从已解析的词汇表数据中提取术语集合。

    通用于 JSON 和 YAML 格式的词汇表文件。

    Args:
        data: 已解析的词汇表数据（dict、list 或其他类型）。

    Returns:
        术语集合。
    """
    terms: set[str] = set()

    if isinstance(data, list):
        # 简单列表格式
        for item in data:
            if isinstance(item, str):
                terms.add(item.strip())
    elif isinstance(data, dict):
        # 分类格式
        categories = data.get("categories", {})
        if isinstance(categories, dict):
            for term_list in categories.values():
                if isinstance(term_list, list):
                    for term in term_list:
                        if isinstance(term, str):
                            terms.add(term.strip())

        flat = data.get("flat_terms", [])
        if isinstance(flat, list):
            for term in flat:
                if isinstance(term, str):
                    terms.add(term.strip())

    return terms
