"""提示词加载器 —— 从 YAML 文件加载策略提示词模板。

每个 YAML 文件包含完整的策略提示词定义：
    - system_prompt: 系统提示词
    - user_template: 用户消息模板（含 {query}, {history} 等占位符）
    - metadata: 策略元数据（名称、阶段、成本、触发条件）
    - output_format: 输出类型（text / json）

加载后的提示词缓存在模块级字典中，避免重复 I/O。

Usage::

    from app.services.prompt_loader import load_prompt

    prompt = load_prompt("context_fusion")
    system = prompt["system_prompt"]
    user = prompt["user_template"].format(query=query, history=history)
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.logging import get_logger

logger = get_logger(__name__)

# ── 提示词目录 ────────────────────────────────────────────────────────────────

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"

# ── 策略名称 → 文件名映射 ─────────────────────────────────────────────────────
# 当策略名称与文件名不完全一致时在此维护映射。

# Phase 1 当前仅上线上下文融合提示词，后续 Phase 2 策略在此追加。
_STRATEGY_FILE_MAP: dict[str, str] = {
    "context_fusion": "context_fusion.yaml",
}


# ── 公共 API ──────────────────────────────────────────────────────────────────


@lru_cache(maxsize=32)
def load_prompt(strategy_name: str) -> dict[str, Any]:
    """加载指定策略的提示词定义。

    结果被 LRU 缓存 —— 同一进程内同一策略仅读取文件一次。

    Args:
        strategy_name: 策略标识符，如 ``"context_fusion"``、``"normalize_rewrite"``。

    Returns:
        包含 ``system_prompt``、``user_template``、``metadata`` 等字段的字典。

    Raises:
        FileNotFoundError: 提示词文件不存在。
        yaml.YAMLError: YAML 格式无效。
        KeyError: 策略名称未注册到 ``_STRATEGY_FILE_MAP`` 中。
    """
    filename = _STRATEGY_FILE_MAP.get(strategy_name)
    if filename is None:
        raise KeyError(
            f"Unknown prompt strategy: '{strategy_name}'. "
            f"Available: {list(_STRATEGY_FILE_MAP.keys())}"
        )

    file_path = _PROMPTS_DIR / filename
    return _load_yaml_prompt(file_path, strategy_name)


def list_available_prompts() -> list[str]:
    """列出所有可用的提示词策略名称。"""
    return sorted(_STRATEGY_FILE_MAP.keys())


def get_prompts_dir() -> Path:
    """返回提示词目录的路径。"""
    return _PROMPTS_DIR


# ── 内部 ──────────────────────────────────────────────────────────────────────


def _load_yaml_prompt(file_path: Path, strategy_name: str) -> dict[str, Any]:
    """从 YAML 文件加载并验证提示词定义。"""
    if not file_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {file_path} (strategy: {strategy_name})")

    try:
        with open(file_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        logger.error("prompt_load_failed", path=str(file_path), error=str(exc))
        raise

    if not isinstance(data, dict):
        raise ValueError(
            f"Invalid prompt file format in {file_path}: expected a YAML mapping, "
            f"got {type(data).__name__}"
        )

    # 基本验证：提示词文件应至少包含 system_prompt 和 user_template 之一
    has_system = "system_prompt" in data
    has_user = "user_template" in data
    if not has_system and not has_user:
        raise ValueError(
            f"Prompt file {file_path} must contain at least one of "
            f"'system_prompt' or 'user_template'"
        )

    logger.debug("prompt_loaded", strategy=strategy_name, path=str(file_path))
    return data


# ═══════════════════════════════════════════════════════════════════════════════
# PromptLoader 三层降级加载器
# ═══════════════════════════════════════════════════════════════════════════════


class PromptLoader:
    """三层降级提示词加载器。

    优先级：环境变量 > YAML Catalog > 代码默认值

    提供：
      - ``load(strategy_name) -> str`` —— 三层降级加载
      - ``validate_all()`` —— 启动时模板占位符验证
      - ``all_versions(filter_names) -> dict[str, str]`` —— 版本追踪

    Usage::

        loader = PromptLoader()
        template = loader.load("normalize")      # 返回模板字符串
        loader.validate_all()                     # 启动时验证占位符
        versions = loader.all_versions()          # 获取版本信息
    """

    # ── 代码默认模板（最低优先级） ─────────────────────────────────────────

    DEFAULT_PROMPT_TEMPLATE: dict[str, str] = {
        "intent_classification": (
            "你是查询意图分类器。分析用户查询，判断意图类型和复杂度。\n\n"
            "## 意图类型\n"
            "从以下类型中选择最匹配的一种：factual（事实型）、analytical（分析型）、"
            "comparative（比较型）、procedural（操作型）、exploratory（探索型）、"
            "chitchat（闲聊型）、ambiguous（模糊查询）。\n\n"
            "## 复杂度评分 (1-10)\n"
            "1-2：简单事实查询；3-5：中等复杂度；6-8：高复杂度；9-10：极高复杂度。\n\n"
            "查询：{query}\n\n"
            '请输出 JSON：{{"intent": "<类型>", "complexity": <1-10>}}'
        ),
        "context_fusion": (
            "结合对话历史将含指代词的查询改写为独立完整的查询。\n\n"
            "## 改写规则\n"
            "1. 指代消解：将所有指代词替换为对话历史中对应的具体实体\n"
            "2. 主题补全：如果用户省略了当前讨论的主题，从历史中补全\n"
            "3. 保持意图：不要改变用户的原始意图和问题方向\n"
            "4. 不要添加历史中不存在的信息\n"
            "5. 如果当前查询已经是独立完整的，原样返回\n\n"
            "{vocabulary}\n"
            "## 对话历史\n{history}\n\n"
            "## 当前用户查询\n{query}\n\n"
            "请输出改写后的独立查询："
        ),
        "normalize": (
            "将用户查询规范化为标准书面语。修正错别字、去除冗余词、补全省略。\n\n"
            "## 改写规则\n"
            "1. 口语转书面：将口语化表达转为正式书面语\n"
            "2. 错别字修正：修正明显的错别字和拼写错误\n"
            "3. 冗余词去除：去除无意义的语气词、填充词\n"
            "4. 省略补全：补全省略的主语、宾语，使查询语义完整\n"
            "5. 保持原意：不添加用户未提及的信息\n"
            "6. 保护词保留：用占位符标记的术语必须原样保留\n\n"
            "{vocabulary}\n"
            "## 保护词（必须原样保留）\n{protected_terms}\n\n"
            "查询：{query}\n\n"
            "请输出规范化查询："
        ),
        "term_align": (
            "将查询中的口语化表达替换为正式专业术语。\n\n"
            "## 改写规则\n"
            "1. 术语替换：将非正式/口语化表达替换为正式专业术语\n"
            "2. 领域适配：根据查询上下文选择最合适的领域术语\n"
            "3. 保持语义：替换后的查询语义必须与原查询一致\n"
            "4. 不过度翻译：已是正式术语的表达保持不变\n"
            "5. 保护词保留：用占位符标记的术语必须原样保留\n\n"
            "{vocabulary}\n"
            "## 保护词（必须原样保留）\n{protected_terms}\n\n"
            "查询：{query}\n\n"
            "请输出术语对齐后的查询："
        ),
        "expand": (
            "对简短模糊的查询进行语义扩展，补充同义词和相关维度。\n\n"
            "## 扩展规则\n"
            "1. 补充同义词：为核心概念补充常见同义词和近义表达\n"
            "2. 添加上位概念：补充更广泛的上位概念以扩大检索范围\n"
            "3. 关联维度：补充与查询密切相关的维度\n"
            "4. 不过度扩展：查询已具体明确时保持原样\n"
            "5. 围绕原意图：不引入与原始查询无关的概念\n"
            "6. 保护词保留：用占位符标记的术语必须原样保留\n\n"
            "{vocabulary}\n"
            "## 保护词（必须原样保留）\n{protected_terms}\n\n"
            "查询：{query}\n\n"
            "请输出扩展后的查询："
        ),
        "context_verification": (
            "你是一个上下文相关性判断助手。请判断以下查询的答案是否依赖于当前对话历史。\n\n"
            "## 判断标准\n"
            '- 依赖上下文（context_dependent: true）：查询中包含指代词（"刚才"、'
            '"前面提到"、"那个"等）、省略了前文才有的主题、'
            "或答案必须结合对话历史才能给出\n"
            "- 不依赖上下文（context_dependent: false）：查询是独立的、自包含的通用问题，"
            "任何人都可以在没有对话历史的情况下理解和回答\n\n"
            "## 当前对话历史\n{history}\n\n"
            "## 待判断的查询\n{query}\n\n"
            '请输出 JSON：{{"context_dependent": <true 或 false>, '
            '"reasoning": "<一句话说明判断依据>"}}'
        ),
        "quality_evaluation": (
            "评估改写质量。\n\n"
            "## 评估维度 (每项 1-5 分)\n"
            "1. semantic_preservation：改写是否完整保留了原始查询的语义和意图\n"
            "2. clarity_improvement：改写后的表达是否比原始查询更清晰明确\n"
            "3. information_gain：改写是否有效补充了有助于检索的关联信息\n"
            "4. term_accuracy：术语使用是否准确、与知识库用词一致\n"
            "5. retrievability：改写后的查询是否更利于向量检索命中相关文档\n\n"
            "## 总体判定 (verdict)\n"
            "excellent / good / marginal / poor\n\n"
            "原始查询：{query}\n"
            "改写结果：{rewritten}\n\n"
            '请输出 JSON：{{"semantic_preservation": N, "clarity_improvement": N, '
            '"information_gain": N, "term_accuracy": N, "retrievability": N, '
            '"total_score": N, "verdict": "...", "issues": [...]}}'
        ),
    }

    # ── 占位符要求 ──────────────────────────────────────────────────────

    _PLACEHOLDER_REQUIREMENTS: dict[str, list[str]] = {
        "intent_classification": ["query"],
        "context_fusion": ["query", "history"],
        "context_verification": ["query", "history"],
        "normalize": ["query", "protected_terms"],
        "term_align": ["query", "protected_terms"],
        "expand": ["query", "protected_terms"],
        "quality_evaluation": ["query", "rewritten"],
    }

    # ── 构造与初始化 ────────────────────────────────────────────────────

    def __init__(self, catalog_path: Path | None = None):
        """初始化 PromptLoader。

        Args:
            catalog_path: YAML Catalog 文件路径。None 使用默认路径
                          ``backend/prompts/rewrite_prompts.yaml``。
        """
        if catalog_path is None:
            catalog_path = (
                Path(__file__).resolve().parent.parent.parent / "prompts" / "rewrite_prompts.yaml"
            )
        self._catalog_path = catalog_path
        self._catalog: dict[str, dict] = {}
        self._catalog_error: Exception | None = None
        self._load_catalog()

    def _load_catalog(self) -> None:
        """加载并解析 YAML Catalog 文件。

        YAML 不存在时静默降级（catalog 保持空 dict），后续 ``load()`` 回退到默认值。
        解析错误不立即抛出，而是储存起来在首次 ``load()`` 调用时延迟抛出，
        确保构造 PromptLoader 不会因为 Catalog 问题而阻止应用启动。
        """
        if not self._catalog_path.exists():
            logger.debug(
                "prompt_catalog_not_found",
                path=str(self._catalog_path),
            )
            return

        try:
            with open(self._catalog_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            logger.error(
                "prompt_catalog_yaml_error",
                path=str(self._catalog_path),
                error=str(exc),
            )
            self._catalog_error = exc
            return

        if not isinstance(data, dict):
            self._catalog_error = ValueError(
                f"Invalid prompt catalog format in {self._catalog_path}: "
                f"expected a YAML mapping, got {type(data).__name__}"
            )
            return

        if "prompts" not in data:
            self._catalog_error = ValueError(
                f"Prompt catalog missing required 'prompts' key: {self._catalog_path}"
            )
            return

        prompts = data["prompts"]
        if not isinstance(prompts, dict):
            self._catalog_error = ValueError(
                f"Invalid 'prompts' value in catalog {self._catalog_path}: "
                f"expected a dict, got {type(prompts).__name__}"
            )
            return

        self._catalog = prompts
        logger.debug(
            "prompt_catalog_loaded",
            path=str(self._catalog_path),
            strategies=list(self._catalog.keys()),
        )

    # ── 三层降级加载 ────────────────────────────────────────────────────

    def load(self, strategy_name: str, *, vocabulary: str = "") -> str:
        """三层降级加载策略模板。

        优先级：
          1. 环境变量 ``QUERY_REWRITE_PROMPT_<NAME>``（最高）
          2. YAML Catalog（``prompts/rewrite_prompts.yaml``）
          3. 代码默认值 ``DEFAULT_PROMPT_TEMPLATE``（最低）

        Args:
            strategy_name: 策略标识符，如 ``"normalize"``、``"expand"``。
            vocabulary: 可选的词汇表文本，用于替换模板中的
                        ``{vocabulary}`` 占位符。默认为空字符串。

        Returns:
            填充有占位符的模板字符串（``{vocabulary}`` 已替换为
            *vocabulary* 内容）。

        Raises:
            KeyError: 策略名未知（所有三层均未命中）。
        """
        # Tier 1: 环境变量（最高优先级，支持紧急热修复）
        env_var = f"QUERY_REWRITE_PROMPT_{strategy_name.upper()}"
        env_value = os.environ.get(env_var)
        if env_value is not None:
            template = env_value
        elif self._catalog_error is not None:
            # 如果 Catalog 解析失败，延迟抛出错误
            raise self._catalog_error
        elif strategy_name in self._catalog:
            # Tier 2: YAML Catalog
            entry = self._catalog[strategy_name]
            if isinstance(entry, dict) and "template" in entry:
                template = entry["template"]
            elif strategy_name in self.DEFAULT_PROMPT_TEMPLATE:
                # Catalog 中存在但格式不完整，回退到代码默认值
                template = self.DEFAULT_PROMPT_TEMPLATE[strategy_name]
            else:
                raise KeyError(
                    f"Prompt strategy '{strategy_name}' found in catalog but has "
                    f"no valid 'template' field and no code default exists. "
                    f"Available defaults: {list(self.DEFAULT_PROMPT_TEMPLATE.keys())}"
                )
        elif strategy_name in self.DEFAULT_PROMPT_TEMPLATE:
            # Tier 3: 代码默认值
            template = self.DEFAULT_PROMPT_TEMPLATE[strategy_name]
        else:
            raise KeyError(
                f"Unknown prompt strategy: '{strategy_name}'. "
                f"Available: {list(self.DEFAULT_PROMPT_TEMPLATE.keys())}"
            )

        # 注入词汇表（如果模板包含占位符且有词汇表内容）
        if "{vocabulary}" in template and vocabulary:
            template = template.replace("{vocabulary}", vocabulary)
        elif "{vocabulary}" in template:
            template = template.replace("{vocabulary}", "")

        return template

    # ── 启动验证 ────────────────────────────────────────────────────────

    def validate_all(self) -> None:
        """验证所有已加载模板的占位符完整性。

        检查规则：
          - ``{query}`` 为所有策略必需
          - ``{history}`` 为 ``context_fusion`` 必需
          - ``{protected_terms}`` 为 ``normalize`` / ``term_align`` / ``expand`` 必需
          - ``{rewritten}`` 为 ``quality_evaluation`` 必需

        Raises:
            ValueError: 模板缺少必需占位符，消息包含策略名和缺失变量名。
        """
        for strategy_name, required_vars in self._PLACEHOLDER_REQUIREMENTS.items():
            template = self.load(strategy_name)
            for var in required_vars:
                placeholder = "{" + var + "}"
                if placeholder not in template:
                    raise ValueError(
                        f"Prompt template for strategy '{strategy_name}' is "
                        f"missing required placeholder '{placeholder}'. "
                        f"Template preview: {template[:100]}..."
                    )

    # ── 版本追踪 ────────────────────────────────────────────────────────

    def all_versions(self, filter_names: list[str] | None = None) -> dict[str, str]:
        """返回 YAML Catalog 中的策略版本映射。

        仅返回在 YAML Catalog 中显式配置了版本的条目（代码默认版本不出现）。

        Args:
            filter_names: 要过滤的策略名列表。``None`` 表示返回所有 YAML 条目。

        Returns:
            ``{strategy_name: version}`` 映射。
        """
        result: dict[str, str] = {}
        for name, entry in self._catalog.items():
            if filter_names is not None and name not in filter_names:
                continue
            if isinstance(entry, dict) and "version" in entry:
                result[name] = entry["version"]
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# TermAlignmentLoader 术语对齐表加载器
# ═══════════════════════════════════════════════════════════════════════════════


class TermAlignmentLoader:
    """术语对齐表加载器。

    从 ``prompts/term_alignment.yaml`` 加载术语对齐数据，提供口语→正式术语
    的扁平映射，以及用于注入 LLM Prompt 的 Markdown 表格。

    Usage::

        loader = TermAlignmentLoader()
        term_map = loader.load()              # → {"跑": "运行", ...}
        table_text = loader.as_markdown_table()  # → Markdown 表格字符串

    数据来源（按优先级合并）：
      1. ``general_alignments``   — 通用口语→正式语映射
      2. ``domain_alignments``   — 按领域分类的专业术语对齐
      3. ``technical_alignments`` — 技术口语→标准术语映射
      4. ``alias_to_canonical``  — 别名/俗称→标准写法（多对一归并）
      5. ``negative_patterns``   — 反模式，**不纳入映射**（不应替换的惯用表达）
    """

    # ── 默认路径 ──────────────────────────────────────────────────────────

    _DEFAULT_CATALOG_PATH: Path = (
        Path(__file__).resolve().parent.parent.parent / "prompts" / "term_alignment.yaml"
    )

    # ── 构造 ──────────────────────────────────────────────────────────────

    def __init__(self, catalog_path: str | Path | None = None):
        """初始化 TermAlignmentLoader。

        Args:
            catalog_path: YAML 术语对齐表文件路径。``None`` 使用默认路径
                          ``backend/prompts/term_alignment.yaml``。

        Raises:
            FileNotFoundError: 文件不存在。
            yaml.YAMLError: YAML 格式错误。
        """
        if catalog_path is None:
            self._catalog_path = self._DEFAULT_CATALOG_PATH
        else:
            self._catalog_path = Path(catalog_path)
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        """加载并解析 YAML 术语对齐表文件。"""
        if not self._catalog_path.exists():
            raise FileNotFoundError(f"Term alignment file not found: {self._catalog_path}")

        with open(self._catalog_path, encoding="utf-8") as f:
            self._data = yaml.safe_load(f)

        if not isinstance(self._data, dict):
            raise ValueError(
                f"Invalid term alignment file format in {self._catalog_path}: "
                f"expected a YAML mapping, got {type(self._data).__name__}"
            )

        logger.debug(
            "term_alignment_loaded",
            path=str(self._catalog_path),
            version=self._data.get("version", "unknown"),
        )

    # ── 公共 API ──────────────────────────────────────────────────────────

    def load(self) -> dict[str, str]:
        """返回口语→正式术语的扁平映射字典。

        合并所有对齐来源：
          - ``general_alignments``（通用口语）
          - ``domain_alignments``（各领域专业术语）
          - ``technical_alignments``（技术行话）
          - ``alias_to_canonical``（别名→标准写法）

        ``negative_patterns``（反模式）不纳入映射。

        Returns:
            ``{colloquial_or_alias: formal_or_canonical}`` 扁平字典。

        Example::

            loader = TermAlignmentLoader()
            term_map = loader.load()
            # term_map["跑"]  → "运行"
            # term_map["js"]  → "JavaScript"
        """
        result: dict[str, str] = {}

        # 1) general_alignments
        for entry in self._data.get("general_alignments", []) or []:
            coll = entry.get("colloquial")
            formal = entry.get("formal")
            if coll and formal:
                result[coll] = formal

        # 2) domain_alignments（遍历所有领域）
        domains = self._data.get("domain_alignments", {}) or {}
        for _, entries in domains.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                coll = entry.get("colloquial")
                formal = entry.get("formal")
                if coll and formal:
                    result[coll] = formal

        # 3) technical_alignments
        for entry in self._data.get("technical_alignments", []) or []:
            coll = entry.get("colloquial")
            formal = entry.get("formal")
            if coll and formal:
                result[coll] = formal

        # 4) alias_to_canonical：每个 alias → canonical
        for entry in self._data.get("alias_to_canonical", []) or []:
            canonical = entry.get("canonical")
            if not canonical:
                continue
            for alias in entry.get("aliases", []) or []:
                result[alias] = canonical

        return result

    def as_markdown_table(self) -> str:
        """生成用于注入 LLM Prompt 的 Markdown 术语对齐表格。

        表格列：口语/非正式表达 | 正式术语 | 备注。
        包含所有对齐来源（general + domain + technical + alias），
        排除 ``negative_patterns``（反模式）。

        Returns:
            Markdown 格式的术语对齐参考表格字符串。

        Example::

            loader = TermAlignmentLoader()
            table = loader.as_markdown_table()
            # | 口语/非正式表达 | 正式术语 | 备注 |
            # |------|------|------|
            # | 跑 | 运行 | "跑程序" → "运行程序" |
            # | ... | ... | ... |
        """
        rows: list[tuple[str, str, str]] = []

        # 1) general_alignments
        for entry in self._data.get("general_alignments", []) or []:
            coll = entry.get("colloquial", "")
            formal = entry.get("formal", "")
            note = entry.get("note", "")
            if coll and formal:
                rows.append((coll, formal, note))

        # 2) domain_alignments
        domains = self._data.get("domain_alignments", {}) or {}
        for _, entries in domains.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                coll = entry.get("colloquial", "")
                formal = entry.get("formal", "")
                note = entry.get("note", "")
                if coll and formal:
                    rows.append((coll, formal, note))

        # 3) technical_alignments
        for entry in self._data.get("technical_alignments", []) or []:
            coll = entry.get("colloquial", "")
            formal = entry.get("formal", "")
            note = entry.get("note", "")
            if coll and formal:
                rows.append((coll, formal, note))

        # 4) alias_to_canonical
        for entry in self._data.get("alias_to_canonical", []) or []:
            canonical = entry.get("canonical", "")
            if not canonical:
                continue
            aliases = entry.get("aliases", []) or []
            for alias in aliases:
                note_text = f"别名 → {canonical}"
                rows.append((alias, canonical, note_text))

        if not rows:
            return "（术语对齐表为空）"

        lines: list[str] = [
            "| 口语/非正式表达 | 正式术语 | 备注 |",
            "|------|------|------|",
        ]
        for coll, formal, note in rows:
            # 转义 Markdown 表格中的管道符
            coll_escaped = coll.replace("|", "\\|")
            formal_escaped = formal.replace("|", "\\|")
            note_escaped = note.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {coll_escaped} | {formal_escaped} | {note_escaped} |")

        return "\n".join(lines)

    @property
    def version(self) -> str:
        """返回术语对齐表的版本号。"""
        return self._data.get("version", "unknown")

    @property
    def description(self) -> str:
        """返回术语对齐表的描述文本。"""
        return self._data.get("description", "")

    def as_prompt_text(self) -> str:
        """生成用于注入 LLM Prompt 的术语对齐参考文本。

        包含术语对齐表格和反模式提醒，适合作为 ``{vocabulary}`` 占位符的替换内容。

        Returns:
            适合注入 LLM System/User Prompt 的结构化参考文本。
        """
        parts: list[str] = []

        # 术语对齐表格
        table = self.as_markdown_table()
        parts.append("## 术语对齐参考表")
        parts.append("以下为口语/非正式表达→正式术语的映射，请在术语对齐时优先参考：")
        parts.append(table)

        # 反模式提醒
        negative = self._data.get("negative_patterns", []) or []
        if negative:
            parts.append("")
            parts.append("## 不替换的惯用表达（反模式）")
            parts.append("以下表达在技术语境中已是约定俗成的标准用法，请保持原样：")
            for entry in negative:
                pattern = entry.get("pattern", "")
                reason = entry.get("reason", "")
                if pattern:
                    parts.append(f"- **{pattern}**：{reason}")

        return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# NormalizeVocabularyLoader 规范化重述词汇表加载器
# ═══════════════════════════════════════════════════════════════════════════════


class NormalizeVocabularyLoader:
    """规范化重述词汇表加载器。

    从 ``prompts/normalize_vocabulary.yaml`` 加载规范化规则，提供用于注入
    LLM Prompt 的结构化参考文本。

    Usage::

        loader = NormalizeVocabularyLoader()
        prompt_text = loader.as_prompt_text()  # → 结构化 Prompt 参考文本

    数据来源：
      1. ``filler_words``              — 无意义语气词/填充词（直接删除）
      2. ``redundancy_patterns``       — 冗余表达模式（精简）
      3. ``typo_corrections``          — 常见错别字修正表
      4. ``sentence_normalization``    — 句式规范化（碎片→完整句）
      5. ``punctuation_rules``         — 标点符号规范化规则
      6. ``quantifier_normalization``  — 模糊量词→精确表达
      7. ``temporal_normalization``    — 时间表达规范化
    """

    # ── 默认路径 ──────────────────────────────────────────────────────────

    _DEFAULT_CATALOG_PATH: Path = (
        Path(__file__).resolve().parent.parent.parent / "prompts" / "normalize_vocabulary.yaml"
    )

    # ── 构造 ──────────────────────────────────────────────────────────────

    def __init__(self, catalog_path: str | Path | None = None):
        """初始化 NormalizeVocabularyLoader。

        Args:
            catalog_path: YAML 词汇表文件路径。``None`` 使用默认路径
                          ``backend/prompts/normalize_vocabulary.yaml``。

        Raises:
            FileNotFoundError: 文件不存在。
            yaml.YAMLError: YAML 格式错误。
        """
        if catalog_path is None:
            self._catalog_path = self._DEFAULT_CATALOG_PATH
        else:
            self._catalog_path = Path(catalog_path)
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        """加载并解析 YAML 词汇表文件。"""
        if not self._catalog_path.exists():
            raise FileNotFoundError(f"Normalize vocabulary file not found: {self._catalog_path}")

        with open(self._catalog_path, encoding="utf-8") as f:
            self._data = yaml.safe_load(f)

        if not isinstance(self._data, dict):
            raise ValueError(
                f"Invalid normalize vocabulary file format in {self._catalog_path}: "
                f"expected a YAML mapping, got {type(self._data).__name__}"
            )

        logger.debug(
            "normalize_vocabulary_loaded",
            path=str(self._catalog_path),
            version=self._data.get("version", "unknown"),
        )

    # ── 公共 API ──────────────────────────────────────────────────────────

    @property
    def version(self) -> str:
        """返回词汇表的版本号。"""
        return self._data.get("version", "unknown")

    @property
    def description(self) -> str:
        """返回词汇表的描述文本。"""
        return self._data.get("description", "")

    def as_prompt_text(self) -> str:
        """生成用于注入 LLM Prompt 的规范化参考文本。

        包含填充词列表、冗余模式、错别字修正表、句式规范、标点规则、
        量词/时间规范化等结构化参考内容。

        Returns:
            适合注入 LLM Prompt 的结构化参考文本。
        """
        parts: list[str] = []
        parts.append("## 规范化重述词汇参考")
        parts.append("请在进行查询规范化时参考以下词汇表和规则：")
        parts.append("")

        # 1) filler_words
        fillers = self._data.get("filler_words", []) or []
        if fillers:
            parts.append("### 无意义填充词（应删除）")
            parts.append("以下词语/短语在查询中不承载信息，请直接删除：")
            for entry in fillers:
                word = entry.get("word", "")
                action = entry.get("action", "")
                note = entry.get("note", "")
                example = entry.get("example", "")
                position = entry.get("position", "")
                line = f"- **{word}**"
                if position:
                    line += f"（{position}）"
                line += f" → {action}"
                if note:
                    line += f"（{note}）"
                if example:
                    line += f"  例：{example}"
                parts.append(line)
            parts.append("")

        # 2) redundancy_patterns
        patterns = self._data.get("redundancy_patterns", []) or []
        if patterns:
            parts.append("### 冗余表达精简规则")
            for entry in patterns:
                pattern = entry.get("pattern", "")
                note = entry.get("note", "")
                exception = entry.get("exception", "")
                line = f"- 模式 `{pattern}`"
                if note:
                    line += f"：{note}"
                if exception:
                    line += f"（例外：{exception}）"
                parts.append(line)
            parts.append("")

        # 3) typo_corrections (high confidence only to keep prompt compact)
        typos = self._data.get("typo_corrections", []) or []
        if typos:
            high_conf = [t for t in typos if t.get("confidence") == "high"]
            if high_conf:
                # Limit to avoid bloating the prompt
                displayed = high_conf[:50]
                parts.append("### 常见错别字修正（高置信度）")
                parts.append("| 错误写法 | 正确写法 |")
                parts.append("|------|------|")
                for entry in displayed:
                    wrong = entry.get("wrong", "").replace("|", "\\|")
                    correct = entry.get("correct", "").replace("|", "\\|")
                    parts.append(f"| {wrong} | {correct} |")
                if len(high_conf) > 50:
                    parts.append(f"（共 {len(high_conf)} 条，仅展示前 50 条）")
                parts.append("")

        # 4) quantifier_normalization
        quantifiers = self._data.get("quantifier_normalization", []) or []
        if quantifiers:
            parts.append("### 模糊量词→精确表达")
            parts.append("| 口语 | 正式表达 |")
            parts.append("|------|------|")
            for entry in quantifiers:
                coll = entry.get("colloquial", "").replace("|", "\\|")
                formal = entry.get("formal", "").replace("|", "\\|")
                if coll and formal:
                    parts.append(f"| {coll} | {formal} |")
            parts.append("")

        # 5) temporal_normalization
        temporals = self._data.get("temporal_normalization", []) or []
        if temporals:
            parts.append("### 时间表达规范化")
            parts.append("| 口语 | 正式表达 |")
            parts.append("|------|------|")
            for entry in temporals:
                coll = entry.get("colloquial", "").replace("|", "\\|")
                formal = entry.get("formal", "").replace("|", "\\|")
                if coll and formal:
                    parts.append(f"| {coll} | {formal} |")
            parts.append("")

        # 6) punctuation_rules (summary)
        punct = self._data.get("punctuation_rules", []) or []
        if punct:
            parts.append("### 标点符号规范")
            for entry in punct:
                pattern = entry.get("pattern", "")
                action = entry.get("action", "")
                note = entry.get("note", "")
                line = f"- {pattern} → {action}"
                if note:
                    line += f"（{note}）"
                parts.append(line)
            parts.append("")

        # 7) sentence_normalization (summary)
        sent_norms = self._data.get("sentence_normalization", []) or []
        if sent_norms:
            parts.append("### 句式规范化原则")
            for entry in sent_norms:
                pattern = entry.get("pattern", "")
                action = entry.get("action", "")
                rules = entry.get("rules", []) or []
                line = f"- {pattern} → {action}"
                parts.append(line)
                for rule in rules:
                    parts.append(f"  - {rule}")
            parts.append("")

        return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# ContextFusionVocabularyLoader 上下文融合词汇表加载器
# ═══════════════════════════════════════════════════════════════════════════════


class ContextFusionVocabularyLoader:
    """上下文融合词汇表加载器。

    从 ``prompts/context_fusion_vocabulary.yaml`` 加载领域术语、缩写映射、
    同义表达组和上下文消歧规则，提供用于注入 LLM Prompt 的结构化参考文本。

    Usage::

        loader = ContextFusionVocabularyLoader()
        prompt_text = loader.as_prompt_text()  # → 结构化 Prompt 参考文本

    数据来源：
      1. ``domain_terms``              — 领域核心术语（含同义词、关联）
      2. ``acronym_map``               — 缩写 ↔ 全称双向映射
      3. ``synonym_groups``            — 同义表达组
      4. ``context_disambiguation``    — 上下文消歧规则
    """

    # ── 默认路径 ──────────────────────────────────────────────────────────

    _DEFAULT_CATALOG_PATH: Path = (
        Path(__file__).resolve().parent.parent.parent / "prompts" / "context_fusion_vocabulary.yaml"
    )

    # ── 构造 ──────────────────────────────────────────────────────────────

    def __init__(self, catalog_path: str | Path | None = None):
        """初始化 ContextFusionVocabularyLoader。

        Args:
            catalog_path: YAML 词汇表文件路径。``None`` 使用默认路径
                          ``backend/prompts/context_fusion_vocabulary.yaml``。

        Raises:
            FileNotFoundError: 文件不存在。
            yaml.YAMLError: YAML 格式错误。
        """
        if catalog_path is None:
            self._catalog_path = self._DEFAULT_CATALOG_PATH
        else:
            self._catalog_path = Path(catalog_path)
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        """加载并解析 YAML 词汇表文件。"""
        if not self._catalog_path.exists():
            raise FileNotFoundError(
                f"Context fusion vocabulary file not found: {self._catalog_path}"
            )

        with open(self._catalog_path, encoding="utf-8") as f:
            self._data = yaml.safe_load(f)

        if not isinstance(self._data, dict):
            raise ValueError(
                f"Invalid context fusion vocabulary file format in "
                f"{self._catalog_path}: expected a YAML mapping, "
                f"got {type(self._data).__name__}"
            )

        logger.debug(
            "context_fusion_vocabulary_loaded",
            path=str(self._catalog_path),
            version=self._data.get("version", "unknown"),
        )

    # ── 公共 API ──────────────────────────────────────────────────────────

    @property
    def version(self) -> str:
        """返回词汇表的版本号。"""
        return self._data.get("version", "unknown")

    @property
    def description(self) -> str:
        """返回词汇表的描述文本。"""
        return self._data.get("description", "")

    def as_prompt_text(self) -> str:
        """生成用于注入 LLM Prompt 的上下文融合参考文本。

        包含领域术语表、缩写映射、同义表达组和上下文消歧规则，
        帮助 LLM 在多轮对话中进行准确的指代消解和术语关联。

        Returns:
            适合注入 LLM Prompt 的结构化参考文本。
        """
        parts: list[str] = []
        parts.append("## 上下文融合词汇参考")
        parts.append("请结合以下领域术语知识，在上下文融合时准确理解用户指代：")
        parts.append("")

        # 1) domain_terms — 精简表格（仅 formal + context_synonyms + domain）
        domain_terms = self._data.get("domain_terms", []) or []
        if domain_terms:
            parts.append("### 领域核心术语")
            parts.append("| 正式名称 | 中文译名 | 上下文同义表达 | 领域 |")
            parts.append("|------|------|------|------|")
            for term in domain_terms:
                formal = term.get("formal", "").replace("|", "\\|")
                chinese = term.get("chinese", "").replace("|", "\\|")
                synonyms = "、".join(term.get("context_synonyms", []) or [])
                synonyms = synonyms.replace("|", "\\|")
                domain = term.get("domain", "").replace("|", "\\|")
                if formal:
                    parts.append(f"| {formal} | {chinese} | {synonyms} | {domain} |")
            parts.append("")

        # 2) acronym_map — 精简为常见缩写（限制数量避免 Prompt 过长）
        acronyms = self._data.get("acronym_map", {}) or {}
        if acronyms:
            # 截取前 30 个最常见的缩写
            acronym_items = list(acronyms.items())[:30]
            parts.append("### 缩写→全称映射")
            parts.append("| 缩写 | 全称 |")
            parts.append("|------|------|")
            for abbr, full in acronym_items:
                abbr_s = str(abbr).replace("|", "\\|")
                full_s = str(full).replace("|", "\\|")
                parts.append(f"| {abbr_s} | {full_s} |")
            if len(acronyms) > 30:
                parts.append(f"（共 {len(acronyms)} 条，仅展示前 30 条）")
            parts.append("")

        # 3) synonym_groups — 同义表达组（精简）
        syn_groups = self._data.get("synonym_groups", []) or []
        if syn_groups:
            parts.append("### 同义表达组（组内各表达语义等价）")
            for group in syn_groups[:15]:  # 限制数量
                group_name = group.get("group", "")
                terms = group.get("terms", []) or []
                if group_name and terms:
                    terms_str = "、".join(terms[:8])
                    parts.append(f"- **{group_name}**：{terms_str}")
            if len(syn_groups) > 15:
                parts.append(f"（共 {len(syn_groups)} 组，仅展示前 15 组）")
            parts.append("")

        # 4) context_disambiguation — 消歧规则（精简）
        disambig = self._data.get("context_disambiguation", []) or []
        if disambig:
            parts.append("### 上下文消歧规则")
            parts.append("当遇到以下歧义术语时，根据对话历史中的关键词判断正确含义：")
            for entry in disambig:
                term = entry.get("ambiguous_term", "")
                contexts = entry.get("contexts", []) or []
                if term and contexts:
                    parts.append(f"- **{term}**：")
                    for ctx in contexts:
                        keywords = "、".join(ctx.get("context_keywords", []) or [])
                        meaning = ctx.get("meaning", "")
                        parts.append(f"  - 若涉及 {keywords} → {meaning}")
            parts.append("")

        return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# 模块级缓存辅助函数
# ═══════════════════════════════════════════════════════════════════════════════


@lru_cache(maxsize=1)
def _load_term_alignment_vocabulary() -> str:
    """加载并缓存术语对齐表 Prompt 参考文本。

    通过 ``TermAlignmentLoader`` 解析 YAML 并生成 Markdown 表格和反模式
    提醒文本。结果被 LRU 缓存 —— 进程生命周期内仅加载一次。

    Returns:
        结构化 Prompt 参考文本。加载失败时返回空字符串。
    """
    try:
        loader = TermAlignmentLoader()
        return loader.as_prompt_text()
    except Exception:
        # 术语对齐表加载失败不应阻止重写，静默降级
        return ""
