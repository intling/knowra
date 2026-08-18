"""提示词加载器测试 —— 从 YAML 文件加载策略提示词。

Phase 1 当前仅上线 context_fusion 提示词，后续 Phase 2 策略追加后扩展此测试文件。

测试覆盖：
- 正常路径：加载 context_fusion 提示词、所有注册提示词均可加载
- 错误处理：未知策略名、缺失文件、无效 YAML
- 缓存行为：同一策略多次调用返回相同对象（LRU 缓存）
- ContextRewriter 集成：默认从 YAML 加载、自定义提示词覆盖

模块二新增 PromptLoader 类测试：
- 三层降级加载（环境变量 → YAML Catalog → 代码默认值）
- 启动验证（模板占位符完整性检查）
- 版本追踪（all_versions 过滤）
- 异常降级（YAML 不存在/格式错误）
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from app.services.prompt_loader import (
    _STRATEGY_FILE_MAP,
    ContextFusionVocabularyLoader,
    NormalizeVocabularyLoader,
    TermAlignmentLoader,
    get_prompts_dir,
    list_available_prompts,
    load_prompt,
)

# ═══════════════════════════════════════════════════════════════════════════════
# 旧版 load_prompt 测试（Phase 1 函数式 API）
# ═══════════════════════════════════════════════════════════════════════════════


class TestLoadPrompt:
    """验证提示词正常加载。"""

    def test_load_context_fusion_prompt(self):
        """context_fusion 提示词应包含 system_prompt 和 user_template。"""
        prompt = load_prompt("context_fusion")

        assert isinstance(prompt, dict)
        assert "system_prompt" in prompt
        assert "user_template" in prompt
        assert "metadata" in prompt
        assert "version" in prompt
        # system_prompt 至少应包含核心指令关键字
        assert "指代词" in prompt["system_prompt"] or "指代" in prompt["system_prompt"]
        # user_template 应包含占位符
        assert "{history}" in prompt["user_template"]
        assert "{query}" in prompt["user_template"]

    def test_all_listed_prompts_are_loadable(self):
        """所有注册的提示词文件都应能正常加载。"""
        names = list_available_prompts()
        assert len(names) > 0, "至少应注册一个提示词"
        for name in names:
            prompt = load_prompt(name)
            assert isinstance(prompt, dict)
            assert "version" in prompt
            has_content = "system_prompt" in prompt or "user_template" in prompt
            assert has_content, f"Prompt '{name}' has neither system_prompt nor user_template"


# ═══════════════════════════════════════════════════════════════════════════════
# 错误处理测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestLoadPromptErrors:
    """验证加载失败的错误处理。"""

    def test_unknown_strategy_raises_key_error(self):
        """未知策略名应抛出 KeyError 并提供可用策略列表。"""
        with pytest.raises(KeyError, match="Unknown prompt strategy"):
            load_prompt("nonexistent_strategy")

    def test_missing_file_raises_file_not_found(self):
        """文件缺失时应抛出 FileNotFoundError。"""
        with (
            patch.dict(_STRATEGY_FILE_MAP, {"test_missing": "nonexistent.yaml"}, clear=False),
            pytest.raises(FileNotFoundError, match="Prompt file not found"),
        ):
            load_prompt("test_missing")

    def test_invalid_yaml_raises_yaml_error(self):
        """无效 YAML 文件应抛出 yaml.YAMLError。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_file = Path(tmpdir) / "bad.yaml"
            bad_file.write_text(": invalid: yaml: : :", encoding="utf-8")

            with (
                patch.object(
                    __import__("app.services.prompt_loader", fromlist=["_PROMPTS_DIR"]),
                    "_PROMPTS_DIR",
                    Path(tmpdir),
                ),
                patch.dict(_STRATEGY_FILE_MAP, {"test_bad_yaml": "bad.yaml"}, clear=False),
                pytest.raises(yaml.YAMLError),
            ):
                load_prompt("test_bad_yaml")


# ═══════════════════════════════════════════════════════════════════════════════
# 缓存行为测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestPromptCache:
    """验证 LRU 缓存行为。"""

    def test_subsequent_calls_return_same_object(self):
        """同一策略的多次调用应返回完全相同的对象（引用相等）。"""
        prompt1 = load_prompt("context_fusion")
        prompt2 = load_prompt("context_fusion")

        assert prompt1 is prompt2


# ═══════════════════════════════════════════════════════════════════════════════
# ContextRewriter 集成测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestContextRewriterIntegration:
    """验证 ContextRewriter 与 PromptLoader 的集成。"""

    def test_context_rewriter_loads_default_prompt_from_yaml(self):
        """不带自定义提示词构造时，应通过 PromptLoader 加载默认提示词。"""
        from unittest.mock import MagicMock

        from app.services.context_rewriter import ContextRewriter

        mock_adapter = MagicMock()
        cr = ContextRewriter(chat_adapter=mock_adapter)

        assert len(cr._prompt_template) > 0
        assert "{history}" in cr._prompt_template
        assert "{query}" in cr._prompt_template

    def test_context_rewriter_custom_prompt_overrides_yaml(self):
        """传入自定义提示词时，应覆盖 PromptLoader 加载的默认提示词。"""
        from unittest.mock import MagicMock

        from app.services.context_rewriter import ContextRewriter

        mock_adapter = MagicMock()
        custom_template = "Custom template with {history} and {query}"

        cr = ContextRewriter(
            chat_adapter=mock_adapter,
            prompt_template=custom_template,
        )

        assert cr._prompt_template == custom_template


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助工具测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestUtilityFunctions:
    """验证辅助工具函数。"""

    def test_list_available_prompts_returns_sorted_list(self):
        """list_available_prompts 应返回排序后的策略名列表。"""
        names = list_available_prompts()

        assert isinstance(names, list)
        assert len(names) > 0
        assert names == sorted(names)
        assert "context_fusion" in names

    def test_get_prompts_dir_returns_existing_directory(self):
        """get_prompts_dir 应返回存在的目录路径。"""
        prompts_dir = get_prompts_dir()

        assert prompts_dir.exists()
        assert prompts_dir.is_dir()
        assert (prompts_dir / "context_fusion.yaml").exists()


# ════════════════════════════════════════════════════════════════════
# PromptLoader 三层降级 + 版本追踪测试
# ════════════════════════════════════════════════════════════════════
# 以下测试驱动新的 PromptLoader 类实现（区别于旧的 load_prompt 函数）。
# PromptLoader 提供：
#   - load(strategy_name) -> str —— 三层降级加载（环境变量→YAML→代码默认值）
#   - validate_all() —— 启动时模板占位符验证
#   - all_versions(filter_names) -> dict[str, str] —— 版本追踪（仅 YAML 条目）
#
# TDD 红阶段：PromptLoader 类尚未创建，导入失败时设为 None。

try:
    from app.services.prompt_loader import PromptLoader
except ImportError:
    PromptLoader = None  # type: ignore[assignment]


# ── 6 个标准策略名 ─────────────────────────────────────────────────

_STRATEGY_NAMES = [
    "intent_classification",
    "context_fusion",
    "normalize",
    "term_align",
    "expand",
    "quality_evaluation",
]


def _build_catalog(
    prompts: dict | None = None,
    *,
    version: str = "1.0",
) -> str:
    """构建合法的 rewrite_prompts.yaml 字符串。"""
    if prompts is None:
        prompts = {
            "intent_classification": {
                "version": "1.2.0",
                "description": "意图分类 + 复杂度评分",
                "template": "你是意图分类器。查询：{query}",
            },
            "context_fusion": {
                "version": "1.1.0",
                "description": "上下文融合",
                "template": "根据对话历史改写查询。\n历史：{history}\n查询：{query}",
            },
            "normalize": {
                "version": "1.0.0",
                "description": "规范化重述",
                "template": "将查询规范化。\n查询：{query}\n保护词：{protected_terms}",
            },
            "term_align": {
                "version": "1.0.0",
                "description": "术语对齐",
                "template": "将术语替换为正式用词。\n查询：{query}\n保护词：{protected_terms}",
            },
            "expand": {
                "version": "1.0.0",
                "description": "扩展重述",
                "template": "扩展查询。\n查询：{query}\n保护词：{protected_terms}",
            },
            "quality_evaluation": {
                "version": "1.0.0",
                "description": "质量评估",
                "template": "评估改写质量。\n原始：{query}\n改写：{rewritten}",
            },
        }
    catalog = {"version": version, "prompts": prompts}
    return yaml.dump(catalog, allow_unicode=True, sort_keys=False)


def _write_temp_catalog(content: str) -> Path:
    """将 YAML 内容写入临时文件。"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", encoding="utf-8", delete=False
    ) as tmp:
        tmp.write(content)
    return Path(tmp.name)


# ── 三层降级加载 ───────────────────────────────────────────────────


class TestPromptLoaderThreeTierLoading:
    """PromptLoader.load() 的三层降级优先级测试。"""

    def test_yaml_catalog_hit_returns_yaml_template(self):
        """YAML Catalog 中存在策略时返回 YAML 模板文本。"""
        yaml_content = _build_catalog()
        path = _write_temp_catalog(yaml_content)
        try:
            loader = PromptLoader(catalog_path=path)
            template = loader.load("normalize")
            assert "规范化" in template
            assert "{query}" in template
        finally:
            path.unlink(missing_ok=True)

    def test_yaml_missing_strategy_falls_back_to_default(self):
        """YAML 中不存在策略时回退到代码默认值。"""
        prompts = {
            "normalize": {
                "version": "1.0.0",
                "description": "test",
                "template": "YAML 模板 {query} {protected_terms}",
            },
        }
        yaml_content = _build_catalog(prompts=prompts)
        path = _write_temp_catalog(yaml_content)
        try:
            loader = PromptLoader(catalog_path=path)
            template = loader.load("intent_classification")
            assert isinstance(template, str)
            assert len(template) > 0
            assert "{query}" in template
        finally:
            path.unlink(missing_ok=True)

    def test_env_var_override_highest_priority(self, monkeypatch):
        """环境变量覆盖时优先级高于 YAML 和代码默认值。"""
        yaml_content = _build_catalog()
        path = _write_temp_catalog(yaml_content)
        env_value = "环境变量紧急热修复模板 {query} {protected_terms}"
        monkeypatch.setenv("QUERY_REWRITE_PROMPT_NORMALIZE", env_value)
        try:
            loader = PromptLoader(catalog_path=path)
            assert loader.load("normalize") == env_value
        finally:
            path.unlink(missing_ok=True)

    def test_env_var_override_without_yaml(self, monkeypatch):
        """仅环境变量（无 YAML）时返回环境变量值。"""
        env_value = "仅环境变量模板 {query}"
        monkeypatch.setenv("QUERY_REWRITE_PROMPT_INTENT_CLASSIFICATION", env_value)
        loader = PromptLoader(catalog_path=Path("/nonexistent/path.yaml"))
        assert loader.load("intent_classification") == env_value

    def test_code_default_without_yaml_and_env(self):
        """无 YAML 无环境变量时返回代码默认值。"""
        loader = PromptLoader(catalog_path=Path("/nonexistent/path.yaml"))
        for name in _STRATEGY_NAMES:
            template = loader.load(name)
            assert isinstance(template, str)
            assert len(template) > 0
            assert "{query}" in template, f"策略 '{name}' 默认模板缺少 {{query}} 占位符"


# ── 启动验证 ───────────────────────────────────────────────────────


class TestPromptLoaderValidation:
    """PromptLoader.validate_all() 的模板占位符验证。"""

    def test_passes_when_all_templates_complete(self):
        """所有模板包含必需占位符时无异常。"""
        yaml_content = _build_catalog()
        path = _write_temp_catalog(yaml_content)
        try:
            loader = PromptLoader(catalog_path=path)
            loader.validate_all()
        finally:
            path.unlink(missing_ok=True)

    def test_passes_with_code_defaults_only(self):
        """仅代码默认值（无 YAML）时验证通过。"""
        loader = PromptLoader(catalog_path=Path("/nonexistent/path.yaml"))
        loader.validate_all()

    def test_raises_when_query_placeholder_missing(self):
        """缺少 {query} 时抛出 ValueError，消息含策略名和缺失变量名。"""
        prompts = {
            "normalize": {
                "version": "1.0.0",
                "description": "缺少 query",
                "template": "只有保护词 {protected_terms}",
            },
        }
        yaml_content = _build_catalog(prompts=prompts)
        path = _write_temp_catalog(yaml_content)
        try:
            loader = PromptLoader(catalog_path=path)
            with pytest.raises(ValueError, match="normalize"):
                loader.validate_all()
            with pytest.raises(ValueError, match="query"):
                loader.validate_all()
        finally:
            path.unlink(missing_ok=True)

    def test_raises_when_history_missing_for_context_fusion(self):
        """context_fusion 缺少 {history} 时抛出 ValueError。"""
        prompts = {
            "context_fusion": {
                "version": "1.0.0",
                "description": "缺少 history",
                "template": "查询：{query}",
            },
        }
        yaml_content = _build_catalog(prompts=prompts)
        path = _write_temp_catalog(yaml_content)
        try:
            loader = PromptLoader(catalog_path=path)
            with pytest.raises(ValueError, match="context_fusion"):
                loader.validate_all()
            with pytest.raises(ValueError, match="history"):
                loader.validate_all()
        finally:
            path.unlink(missing_ok=True)

    def test_raises_when_protected_terms_missing(self):
        """normalize/term_align/expand 缺少 {protected_terms} 时抛出 ValueError。"""
        for strategy in ("normalize", "term_align", "expand"):
            prompts = {
                strategy: {
                    "version": "1.0.0",
                    "description": f"缺少 protected_terms - {strategy}",
                    "template": "查询：{query}",
                },
            }
            yaml_content = _build_catalog(prompts=prompts)
            path = _write_temp_catalog(yaml_content)
            try:
                loader = PromptLoader(catalog_path=path)
                with pytest.raises(ValueError, match=strategy):
                    loader.validate_all()
                with pytest.raises(ValueError, match="protected_terms"):
                    loader.validate_all()
            finally:
                path.unlink(missing_ok=True)


# ── 版本追踪 ───────────────────────────────────────────────────────


class TestPromptLoaderVersionTracking:
    """PromptLoader.all_versions() 的版本过滤测试。"""

    def test_filter_returns_only_requested_strategies(self):
        """filter_names 仅返回 YAML 中配置的、且在 filter_names 中的策略。"""
        yaml_content = _build_catalog()
        path = _write_temp_catalog(yaml_content)
        try:
            loader = PromptLoader(catalog_path=path)
            versions = loader.all_versions(filter_names=["intent_classification", "normalize"])
            assert isinstance(versions, dict)
            assert "intent_classification" in versions
            assert "normalize" in versions
            assert "expand" not in versions
            assert "term_align" not in versions
            assert versions["intent_classification"] == "1.2.0"
            assert versions["normalize"] == "1.0.0"
        finally:
            path.unlink(missing_ok=True)

    def test_none_filter_returns_all_yaml_entries(self):
        """filter_names=None 返回 YAML 中所有策略版本。"""
        yaml_content = _build_catalog()
        path = _write_temp_catalog(yaml_content)
        try:
            loader = PromptLoader(catalog_path=path)
            versions = loader.all_versions(filter_names=None)
            for name in _STRATEGY_NAMES:
                assert name in versions, f"'{name}' 应在 all_versions 结果中"
            assert len(versions) >= len(_STRATEGY_NAMES)
        finally:
            path.unlink(missing_ok=True)

    def test_excludes_code_defaults(self):
        """代码默认版本不出现在 all_versions 中。"""
        prompts = {
            "normalize": {
                "version": "1.5.0",
                "description": "test",
                "template": "{query} {protected_terms}",
            },
        }
        yaml_content = _build_catalog(prompts=prompts)
        path = _write_temp_catalog(yaml_content)
        try:
            loader = PromptLoader(catalog_path=path)
            versions = loader.all_versions(filter_names=None)
            assert "normalize" in versions
            assert versions["normalize"] == "1.5.0"
            assert "intent_classification" not in versions
        finally:
            path.unlink(missing_ok=True)

    def test_empty_filter_list_returns_empty_dict(self):
        """filter_names=[] 返回空字典。"""
        yaml_content = _build_catalog()
        path = _write_temp_catalog(yaml_content)
        try:
            loader = PromptLoader(catalog_path=path)
            assert loader.all_versions(filter_names=[]) == {}
        finally:
            path.unlink(missing_ok=True)

    def test_no_yaml_returns_empty_dict(self):
        """无 YAML 时 all_versions 返回空字典。"""
        loader = PromptLoader(catalog_path=Path("/nonexistent/path.yaml"))
        assert loader.all_versions(filter_names=None) == {}


# ── 异常处理 / 降级 ────────────────────────────────────────────────


class TestPromptLoaderErrorHandling:
    """异常场景下的降级与错误处理。"""

    def test_yaml_not_found_falls_back_to_defaults(self):
        """YAML Catalog 不存在时不抛出异常，使用代码默认值。"""
        loader = PromptLoader(catalog_path=Path("/nonexistent/path.yaml"))
        for name in _STRATEGY_NAMES:
            template = loader.load(name)
            assert isinstance(template, str)
            assert len(template) > 0

    def test_yaml_format_error_raises(self):
        """YAML 格式错误时抛出 yaml.YAMLError 或 ValueError。"""
        bad_yaml = 'version: "1.0"\nprompts:\n  normalize:\n    template: "未闭合引号\n'
        path = _write_temp_catalog(bad_yaml)
        try:
            loader = PromptLoader(catalog_path=path)
            with pytest.raises((yaml.YAMLError, ValueError)):
                loader.load("normalize")
        finally:
            path.unlink(missing_ok=True)

    def test_missing_prompts_key_raises(self):
        """YAML 缺少 'prompts' 顶层键时抛出 ValueError。"""
        bad_yaml = yaml.dump({"version": "1.0", "not_prompts": {}})
        path = _write_temp_catalog(bad_yaml)
        try:
            loader = PromptLoader(catalog_path=path)
            with pytest.raises(ValueError, match="prompts"):
                loader.load("normalize")
        finally:
            path.unlink(missing_ok=True)

    def test_prompts_not_a_dict_raises(self):
        """prompts 不是 dict 时抛出 ValueError。"""
        bad_yaml = yaml.dump({"version": "1.0", "prompts": [1, 2, 3]})
        path = _write_temp_catalog(bad_yaml)
        try:
            loader = PromptLoader(catalog_path=path)
            with pytest.raises(ValueError):
                loader.load("normalize")
        finally:
            path.unlink(missing_ok=True)

    def test_empty_prompts_falls_back_to_defaults(self):
        """prompts 为空时所有策略回退到代码默认值。"""
        catalog = yaml.dump({"version": "1.0", "prompts": {}})
        path = _write_temp_catalog(catalog)
        try:
            loader = PromptLoader(catalog_path=path)
            for name in _STRATEGY_NAMES:
                template = loader.load(name)
                assert isinstance(template, str)
                assert len(template) > 0
                assert "{query}" in template
        finally:
            path.unlink(missing_ok=True)

    def test_default_catalog_path_fallback(self):
        """未提供 catalog_path 时使用默认路径（测试环境中文件不存在，降级为默认值）。"""
        loader = PromptLoader()
        template = loader.load("normalize")
        assert isinstance(template, str)
        assert len(template) > 0


# ── 边界情况 ───────────────────────────────────────────────────────


class TestPromptLoaderEdgeCases:
    """PromptLoader 边界情况测试。"""

    def test_unknown_strategy_raises_key_error(self):
        """未知策略名抛出 KeyError。"""
        loader = PromptLoader(catalog_path=Path("/nonexistent/path.yaml"))
        with pytest.raises(KeyError, match="unknown_strategy"):
            loader.load("unknown_strategy")

    def test_load_returns_string(self):
        """load() 返回字符串（非 dict），区别于旧版 load_prompt()。"""
        yaml_content = _build_catalog()
        path = _write_temp_catalog(yaml_content)
        try:
            loader = PromptLoader(catalog_path=path)
            template = loader.load("normalize")
            assert isinstance(template, str)
            assert not isinstance(template, dict)
        finally:
            path.unlink(missing_ok=True)

    def test_multiple_loads_consistent(self):
        """多次调用返回一致结果。"""
        yaml_content = _build_catalog()
        path = _write_temp_catalog(yaml_content)
        try:
            loader = PromptLoader(catalog_path=path)
            assert loader.load("normalize") == loader.load("normalize")
        finally:
            path.unlink(missing_ok=True)

    def test_validate_all_idempotent(self):
        """多次 validate_all() 调用幂等。"""
        yaml_content = _build_catalog()
        path = _write_temp_catalog(yaml_content)
        try:
            loader = PromptLoader(catalog_path=path)
            loader.validate_all()
            loader.validate_all()
            loader.validate_all()
        finally:
            path.unlink(missing_ok=True)

    def test_quality_evaluation_has_rewritten_not_protected_terms(self):
        """quality_evaluation 使用 {rewritten} 而非 {protected_terms}。"""
        yaml_content = _build_catalog()
        path = _write_temp_catalog(yaml_content)
        try:
            loader = PromptLoader(catalog_path=path)
            template = loader.load("quality_evaluation")
            assert "{rewritten}" in template
            loader.validate_all()
        finally:
            path.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TermAlignmentLoader 测试
# ═══════════════════════════════════════════════════════════════════════════════


def _build_term_alignment_yaml(
    general_alignments: list[dict] | None = None,
    domain_alignments: dict | None = None,
    technical_alignments: list[dict] | None = None,
    alias_to_canonical: list[dict] | None = None,
    negative_patterns: list[dict] | None = None,
    *,
    version: str = "1.0.0",
) -> str:
    """构建合法的 term_alignment.yaml 字符串。"""
    data: dict = {
        "version": version,
        "description": "测试用术语对齐表",
        "general_alignments": general_alignments or [],
        "domain_alignments": domain_alignments or {},
        "technical_alignments": technical_alignments or [],
        "alias_to_canonical": alias_to_canonical or [],
        "negative_patterns": negative_patterns or [],
    }
    return yaml.dump(data, allow_unicode=True, sort_keys=False)


def _write_temp_term_alignment(content: str) -> Path:
    """将 YAML 内容写入临时文件。"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", encoding="utf-8", delete=False
    ) as tmp:
        tmp.write(content)
    return Path(tmp.name)


_STANDARD_TERM_ALIGNMENT = _build_term_alignment_yaml(
    general_alignments=[
        {"colloquial": "跑", "formal": "运行", "note": '"跑程序" → "运行程序"'},
        {"colloquial": "装", "formal": "安装", "note": '"装一个库" → "安装一个库"'},
        {"colloquial": "崩了", "formal": "崩溃 / 异常终止", "note": '"程序崩了" → "程序异常终止"'},
    ],
    domain_alignments={
        "software_engineering": [
            {"colloquial": "编译不过", "formal": "编译失败", "note": ""},
            {"colloquial": "调接口", "formal": "调用 API 接口", "note": ""},
        ],
        "database": [
            {"colloquial": "查库", "formal": "查询数据库", "note": ""},
        ],
    },
    technical_alignments=[
        {"colloquial": "造轮子", "formal": "重复实现已有功能", "note": ""},
        {"colloquial": "祖传代码", "formal": "遗留代码", "note": ""},
    ],
    alias_to_canonical=[
        {"canonical": "JavaScript", "aliases": ["js", "JS", "javascript"]},
        {"canonical": "PostgreSQL", "aliases": ["postgres", "pg", "PG"]},
    ],
    negative_patterns=[
        {"pattern": "hello world", "reason": "约定俗成表达", "example": ""},
        {"pattern": "bug", "reason": "约定俗成", "example": ""},
    ],
)


class TestTermAlignmentLoaderLoad:
    """TermAlignmentLoader.load() 的扁平映射测试。"""

    def test_returns_flat_dict(self):
        """load() 返回口语→正式术语的扁平字典。"""
        path = _write_temp_term_alignment(_STANDARD_TERM_ALIGNMENT)
        try:
            loader = TermAlignmentLoader(catalog_path=path)
            term_map = loader.load()
            assert isinstance(term_map, dict)
            assert len(term_map) > 0
        finally:
            path.unlink(missing_ok=True)

    def test_general_alignments_included(self):
        """general_alignments 条目应包含在映射中。"""
        path = _write_temp_term_alignment(_STANDARD_TERM_ALIGNMENT)
        try:
            loader = TermAlignmentLoader(catalog_path=path)
            term_map = loader.load()
            assert term_map["跑"] == "运行"
            assert term_map["装"] == "安装"
            assert term_map["崩了"] == "崩溃 / 异常终止"
        finally:
            path.unlink(missing_ok=True)

    def test_domain_alignments_included(self):
        """domain_alignments 中各领域的术语应合并到映射中。"""
        path = _write_temp_term_alignment(_STANDARD_TERM_ALIGNMENT)
        try:
            loader = TermAlignmentLoader(catalog_path=path)
            term_map = loader.load()
            assert term_map["编译不过"] == "编译失败"
            assert term_map["调接口"] == "调用 API 接口"
            assert term_map["查库"] == "查询数据库"
        finally:
            path.unlink(missing_ok=True)

    def test_technical_alignments_included(self):
        """technical_alignments 应包含在映射中。"""
        path = _write_temp_term_alignment(_STANDARD_TERM_ALIGNMENT)
        try:
            loader = TermAlignmentLoader(catalog_path=path)
            term_map = loader.load()
            assert term_map["造轮子"] == "重复实现已有功能"
            assert term_map["祖传代码"] == "遗留代码"
        finally:
            path.unlink(missing_ok=True)

    def test_alias_to_canonical_included(self):
        """alias_to_canonical 的所有别名都应映射到标准写法。"""
        path = _write_temp_term_alignment(_STANDARD_TERM_ALIGNMENT)
        try:
            loader = TermAlignmentLoader(catalog_path=path)
            term_map = loader.load()
            assert term_map["js"] == "JavaScript"
            assert term_map["JS"] == "JavaScript"
            assert term_map["javascript"] == "JavaScript"
            assert term_map["postgres"] == "PostgreSQL"
            assert term_map["pg"] == "PostgreSQL"
            assert term_map["PG"] == "PostgreSQL"
        finally:
            path.unlink(missing_ok=True)

    def test_negative_patterns_not_included(self):
        """negative_patterns（反模式）不应出现在映射中。"""
        path = _write_temp_term_alignment(_STANDARD_TERM_ALIGNMENT)
        try:
            loader = TermAlignmentLoader(catalog_path=path)
            term_map = loader.load()
            # "hello world" 和 "bug" 是反模式，不应出现在映射中
            assert "hello world" not in term_map
        finally:
            path.unlink(missing_ok=True)


class TestTermAlignmentLoaderAsMarkdownTable:
    """TermAlignmentLoader.as_markdown_table() 测试。"""

    def test_returns_non_empty_string(self):
        """as_markdown_table() 返回非空字符串，含表头。"""
        path = _write_temp_term_alignment(_STANDARD_TERM_ALIGNMENT)
        try:
            loader = TermAlignmentLoader(catalog_path=path)
            table = loader.as_markdown_table()
            assert isinstance(table, str)
            assert len(table) > 0
            assert "口语/非正式表达" in table
            assert "正式术语" in table
        finally:
            path.unlink(missing_ok=True)

    def test_contains_alignment_entries(self):
        """表格应包含具体的对齐条目。"""
        path = _write_temp_term_alignment(_STANDARD_TERM_ALIGNMENT)
        try:
            loader = TermAlignmentLoader(catalog_path=path)
            table = loader.as_markdown_table()
            assert "跑" in table
            assert "运行" in table
            assert "js" in table
            assert "JavaScript" in table
        finally:
            path.unlink(missing_ok=True)

    def test_empty_catalog_returns_placeholder(self):
        """空白术语表时返回占位提示文本。"""
        empty = _build_term_alignment_yaml()
        path = _write_temp_term_alignment(empty)
        try:
            loader = TermAlignmentLoader(catalog_path=path)
            table = loader.as_markdown_table()
            assert isinstance(table, str)
            assert len(table) > 0
        finally:
            path.unlink(missing_ok=True)


class TestTermAlignmentLoaderDefaultPath:
    """TermAlignmentLoader 默认路径测试。"""

    def test_default_constructor_loads_from_default_path(self):
        """不带参数构造时从默认路径 prompts/term_alignment.yaml 加载。"""
        loader = TermAlignmentLoader()
        term_map = loader.load()
        assert isinstance(term_map, dict)
        assert len(term_map) > 0
        # 默认文件中的已知条目
        assert term_map["跑"] == "运行"

    def test_version_property(self):
        """version 属性返回术语对齐表的版本号。"""
        loader = TermAlignmentLoader()
        assert isinstance(loader.version, str)
        assert len(loader.version) > 0

    def test_description_property(self):
        """description 属性返回描述文本。"""
        loader = TermAlignmentLoader()
        assert isinstance(loader.description, str)
        assert len(loader.description) > 0


class TestTermAlignmentLoaderErrors:
    """TermAlignmentLoader 错误处理测试。"""

    def test_file_not_found_raises(self):
        """文件不存在时抛出 FileNotFoundError。"""
        with pytest.raises(FileNotFoundError, match="not found"):
            TermAlignmentLoader(catalog_path="/nonexistent/path/to/term_alignment.yaml")

    def test_invalid_yaml_raises(self):
        """无效 YAML 文件抛出 yaml.YAMLError。"""
        invalid = 'version: "1.0"\ngeneral_alignments:\n  - : : invalid:\n'
        path = _write_temp_term_alignment(invalid)
        try:
            with pytest.raises(yaml.YAMLError):
                TermAlignmentLoader(catalog_path=path)
        finally:
            path.unlink(missing_ok=True)


class TestTermAlignmentLoaderCustomPath:
    """TermAlignmentLoader 自定义路径测试。"""

    def test_custom_catalog_path_as_string(self):
        """catalog_path 接受字符串路径。"""
        path_str = str(_write_temp_term_alignment(_STANDARD_TERM_ALIGNMENT))
        try:
            loader = TermAlignmentLoader(catalog_path=path_str)
            term_map = loader.load()
            assert term_map["跑"] == "运行"
        finally:
            Path(path_str).unlink(missing_ok=True)


class TestTermAlignmentLoaderEdgeCases:
    """TermAlignmentLoader 边界情况测试。"""

    def test_missing_general_alignments_key(self):
        """YAML 缺少 general_alignments 键时不报错，返回空映射。"""
        minimal = yaml.dump({"version": "1.0.0"}, allow_unicode=True)
        path = _write_temp_term_alignment(minimal)
        try:
            loader = TermAlignmentLoader(catalog_path=path)
            term_map = loader.load()
            assert isinstance(term_map, dict)
            assert len(term_map) == 0
        finally:
            path.unlink(missing_ok=True)

    def test_domain_alignments_scalar_skipped(self):
        """domain_alignments 的值若非列表则跳过。"""
        content = _build_term_alignment_yaml(
            general_alignments=[{"colloquial": "跑", "formal": "运行", "note": ""}],
            domain_alignments={"bad_domain": "not_a_list"},
        )
        path = _write_temp_term_alignment(content)
        try:
            loader = TermAlignmentLoader(catalog_path=path)
            term_map = loader.load()
            assert term_map["跑"] == "运行"
            assert len(term_map) == 1  # bad_domain 被跳过
        finally:
            path.unlink(missing_ok=True)

    def test_alias_to_canonical_missing_canonical_skipped(self):
        """alias 条目缺少 canonical 时跳过该条。"""
        content = _build_term_alignment_yaml(
            alias_to_canonical=[
                {"aliases": ["gh"]},  # 无 canonical
                {"canonical": "GitHub", "aliases": ["gh", "github"]},
            ],
        )
        path = _write_temp_term_alignment(content)
        try:
            loader = TermAlignmentLoader(catalog_path=path)
            term_map = loader.load()
            # 第一个条目不产生映射，第二个产生
            assert term_map["gh"] == "GitHub"
            assert term_map["github"] == "GitHub"
            assert len(term_map) == 2
        finally:
            path.unlink(missing_ok=True)

    def test_load_idempotent(self):
        """多次 load() 调用返回一致结果。"""
        path = _write_temp_term_alignment(_STANDARD_TERM_ALIGNMENT)
        try:
            loader = TermAlignmentLoader(catalog_path=path)
            m1 = loader.load()
            m2 = loader.load()
            assert m1 == m2
        finally:
            path.unlink(missing_ok=True)

    def test_as_markdown_table_escapes_pipe(self):
        """表格中的管道符应被转义。"""
        content = _build_term_alignment_yaml(
            general_alignments=[
                {"colloquial": "挂了", "formal": "崩溃 | 停止响应 | 宕机", "note": ""},
            ],
        )
        path = _write_temp_term_alignment(content)
        try:
            loader = TermAlignmentLoader(catalog_path=path)
            table = loader.as_markdown_table()
            # 管道符应被转义
            assert "崩溃 \\| 停止响应 \\| 宕机" in table
        finally:
            path.unlink(missing_ok=True)


class TestTermAlignmentLoaderAsPromptText:
    """TermAlignmentLoader.as_prompt_text() 测试。"""

    def test_returns_non_empty_string(self):
        """as_prompt_text() 返回非空字符串。"""
        path = _write_temp_term_alignment(_STANDARD_TERM_ALIGNMENT)
        try:
            loader = TermAlignmentLoader(catalog_path=path)
            text = loader.as_prompt_text()
            assert isinstance(text, str)
            assert len(text) > 0
            assert "术语对齐参考表" in text
        finally:
            path.unlink(missing_ok=True)

    def test_includes_table_and_negative_patterns(self):
        """应包含术语表格和反模式提醒。"""
        path = _write_temp_term_alignment(_STANDARD_TERM_ALIGNMENT)
        try:
            loader = TermAlignmentLoader(catalog_path=path)
            text = loader.as_prompt_text()
            assert "跑" in text
            assert "运行" in text
            assert "不替换的惯用表达" in text
            assert "hello world" in text
        finally:
            path.unlink(missing_ok=True)

    def test_no_negative_patterns_still_works(self):
        """无反模式时仍正常生成文本（不包含反模式章节）。"""
        content = _build_term_alignment_yaml(
            general_alignments=[
                {"colloquial": "跑", "formal": "运行", "note": ""},
            ],
        )
        path = _write_temp_term_alignment(content)
        try:
            loader = TermAlignmentLoader(catalog_path=path)
            text = loader.as_prompt_text()
            assert "不替换的惯用表达" not in text
        finally:
            path.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# NormalizeVocabularyLoader 测试
# ═══════════════════════════════════════════════════════════════════════════════


def _build_normalize_vocabulary_yaml(
    filler_words: list[dict] | None = None,
    redundancy_patterns: list[dict] | None = None,
    typo_corrections: list[dict] | None = None,
    quantifier_normalization: list[dict] | None = None,
    temporal_normalization: list[dict] | None = None,
    punctuation_rules: list[dict] | None = None,
    sentence_normalization: list[dict] | None = None,
    *,
    version: str = "1.0.0",
) -> str:
    """构建合法的 normalize_vocabulary.yaml 字符串。"""
    data: dict = {
        "version": version,
        "description": "测试用规范化词汇表",
        "filler_words": filler_words or [],
        "redundancy_patterns": redundancy_patterns or [],
        "typo_corrections": typo_corrections or [],
        "quantifier_normalization": quantifier_normalization or [],
        "temporal_normalization": temporal_normalization or [],
        "punctuation_rules": punctuation_rules or [],
        "sentence_normalization": sentence_normalization or [],
    }
    return yaml.dump(data, allow_unicode=True, sort_keys=False)


def _write_temp_normalize_vocab(content: str) -> Path:
    """将 YAML 内容写入临时文件。"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", encoding="utf-8", delete=False
    ) as tmp:
        tmp.write(content)
    return Path(tmp.name)


_STANDARD_NORMALIZE_VOCAB = _build_normalize_vocabulary_yaml(
    filler_words=[
        {
            "word": "嗯",
            "position": "sentence_start",
            "action": "delete",
            "note": "",
            "example": '"嗯 怎么配置" → "怎么配置"',
        },
        {"word": "就是说", "position": "anywhere", "action": "delete", "note": "口语填充"},
    ],
    redundancy_patterns=[
        {
            "pattern": "(.+?)一下",
            "action": "replace",
            "replacement": "\\1",
            "note": '"试一下" → "试"',
        },
    ],
    typo_corrections=[
        {"wrong": "在么", "correct": "在吗", "confidence": "high"},
        {"wrong": "按装", "correct": "安装", "confidence": "high"},
        {"wrong": "配制", "correct": "配置", "confidence": "medium"},
    ],
    quantifier_normalization=[
        {"colloquial": "几个", "formal": "多个", "note": ""},
        {"colloquial": "一大堆", "formal": "大量", "note": ""},
    ],
    temporal_normalization=[
        {"colloquial": "刚才", "formal": "刚才 / 上一轮对话中", "note": ""},
    ],
    punctuation_rules=[
        {
            "pattern": "[!！]{2,}",
            "action": "replace",
            "replacement": "！",
            "note": "多个感叹号合并为一个",
        },
    ],
    sentence_normalization=[
        {
            "pattern": "仅由名词/短语组成的碎片查询",
            "action": "expand_to_query",
            "rules": ['若为技术概念名 → 补充"如何使用"'],
        },
    ],
)


class TestNormalizeVocabularyLoader:
    """NormalizeVocabularyLoader 基本功能测试。"""

    def test_default_constructor_loads_from_default_path(self):
        """不带参数构造时从默认路径加载。"""
        loader = NormalizeVocabularyLoader()
        assert isinstance(loader.version, str)
        assert len(loader.version) > 0
        assert isinstance(loader.description, str)

    def test_version_property(self):
        """version 属性返回版本号。"""
        path = _write_temp_normalize_vocab(_STANDARD_NORMALIZE_VOCAB)
        try:
            loader = NormalizeVocabularyLoader(catalog_path=path)
            assert loader.version == "1.0.0"
        finally:
            path.unlink(missing_ok=True)

    def test_description_property(self):
        """description 属性返回描述文本。"""
        path = _write_temp_normalize_vocab(_STANDARD_NORMALIZE_VOCAB)
        try:
            loader = NormalizeVocabularyLoader(catalog_path=path)
            assert "测试用" in loader.description
        finally:
            path.unlink(missing_ok=True)

    def test_as_prompt_text_returns_non_empty_string(self):
        """as_prompt_text() 返回非空字符串。"""
        path = _write_temp_normalize_vocab(_STANDARD_NORMALIZE_VOCAB)
        try:
            loader = NormalizeVocabularyLoader(catalog_path=path)
            text = loader.as_prompt_text()
            assert isinstance(text, str)
            assert len(text) > 0
        finally:
            path.unlink(missing_ok=True)

    def test_as_prompt_text_contains_filler_words(self):
        """应包含填充词章节。"""
        path = _write_temp_normalize_vocab(_STANDARD_NORMALIZE_VOCAB)
        try:
            loader = NormalizeVocabularyLoader(catalog_path=path)
            text = loader.as_prompt_text()
            assert "无意义填充词" in text
            assert "嗯" in text
            assert "就是说" in text
        finally:
            path.unlink(missing_ok=True)

    def test_as_prompt_text_contains_typo_table(self):
        """应包含错别字修正表格。"""
        path = _write_temp_normalize_vocab(_STANDARD_NORMALIZE_VOCAB)
        try:
            loader = NormalizeVocabularyLoader(catalog_path=path)
            text = loader.as_prompt_text()
            assert "常见错别字修正" in text
            assert "在么" in text
            assert "在吗" in text
        finally:
            path.unlink(missing_ok=True)

    def test_as_prompt_text_filters_low_confidence_typos(self):
        """仅高置信度错别字出现在表格中。"""
        path = _write_temp_normalize_vocab(_STANDARD_NORMALIZE_VOCAB)
        try:
            loader = NormalizeVocabularyLoader(catalog_path=path)
            text = loader.as_prompt_text()
            # medium confidence 的 "配制" 不应出现
            assert "配制" not in text
        finally:
            path.unlink(missing_ok=True)

    def test_as_prompt_text_contains_quantifiers(self):
        """应包含量词规范化表格。"""
        path = _write_temp_normalize_vocab(_STANDARD_NORMALIZE_VOCAB)
        try:
            loader = NormalizeVocabularyLoader(catalog_path=path)
            text = loader.as_prompt_text()
            assert "模糊量词" in text
            assert "几个" in text
            assert "多个" in text
        finally:
            path.unlink(missing_ok=True)

    def test_as_prompt_text_empty_catalog(self):
        """空词汇表仍正常生成文本。"""
        empty = _build_normalize_vocabulary_yaml()
        path = _write_temp_normalize_vocab(empty)
        try:
            loader = NormalizeVocabularyLoader(catalog_path=path)
            text = loader.as_prompt_text()
            assert isinstance(text, str)
        finally:
            path.unlink(missing_ok=True)

    def test_custom_path_as_string(self):
        """catalog_path 接受字符串路径。"""
        path_str = str(_write_temp_normalize_vocab(_STANDARD_NORMALIZE_VOCAB))
        try:
            loader = NormalizeVocabularyLoader(catalog_path=path_str)
            assert loader.version == "1.0.0"
        finally:
            Path(path_str).unlink(missing_ok=True)


class TestNormalizeVocabularyLoaderErrors:
    """NormalizeVocabularyLoader 错误处理测试。"""

    def test_file_not_found_raises(self):
        """文件不存在时抛出 FileNotFoundError。"""
        with pytest.raises(FileNotFoundError, match="not found"):
            NormalizeVocabularyLoader(catalog_path="/nonexistent/normalize_vocab.yaml")

    def test_invalid_yaml_raises(self):
        """无效 YAML 文件抛出 yaml.YAMLError。"""
        invalid = 'version: "1.0"\nfiller_words:\n  - : : invalid:\n'
        path = _write_temp_normalize_vocab(invalid)
        try:
            with pytest.raises(yaml.YAMLError):
                NormalizeVocabularyLoader(catalog_path=path)
        finally:
            path.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# ContextFusionVocabularyLoader 测试
# ═══════════════════════════════════════════════════════════════════════════════


def _build_cf_vocabulary_yaml(
    domain_terms: list[dict] | None = None,
    acronym_map: dict | None = None,
    synonym_groups: list[dict] | None = None,
    context_disambiguation: list[dict] | None = None,
    *,
    version: str = "1.0.0",
) -> str:
    """构建合法的 context_fusion_vocabulary.yaml 字符串。"""
    data: dict = {
        "version": version,
        "description": "测试用上下文融合词汇表",
        "domain_terms": domain_terms or [],
        "acronym_map": acronym_map or {},
        "synonym_groups": synonym_groups or [],
        "context_disambiguation": context_disambiguation or [],
    }
    return yaml.dump(data, allow_unicode=True, sort_keys=False)


def _write_temp_cf_vocab(content: str) -> Path:
    """将 YAML 内容写入临时文件。"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", encoding="utf-8", delete=False
    ) as tmp:
        tmp.write(content)
    return Path(tmp.name)


_STANDARD_CF_VOCAB = _build_cf_vocabulary_yaml(
    domain_terms=[
        {
            "formal": "Retrieval-Augmented Generation",
            "acronyms": ["RAG"],
            "chinese": "检索增强生成",
            "context_synonyms": ["知识增强检索", "RAG 管线"],
            "domain": "ai",
            "related": ["向量检索", "语义搜索"],
        },
        {
            "formal": "Semantic Search",
            "acronyms": [],
            "chinese": "语义搜索",
            "context_synonyms": ["语义检索", "向量搜索"],
            "domain": "search",
            "related": ["向量数据库", "Embedding"],
        },
    ],
    acronym_map={
        "RAG": "Retrieval-Augmented Generation",
        "LLM": "Large Language Model",
        "DI": "Dependency Injection",
    },
    synonym_groups=[
        {"group": "搜索/检索", "terms": ["搜索", "检索", "查找", "查询"]},
        {"group": "上传/导入", "terms": ["上传", "导入", "添加", "录入"]},
    ],
    context_disambiguation=[
        {
            "ambiguous_term": "RAG",
            "contexts": [
                {
                    "context_keywords": ["检索", "知识库", "向量"],
                    "meaning": "Retrieval-Augmented Generation",
                },
                {"context_keywords": ["清理", "抹布"], "meaning": "Rag（抹布/碎布）"},
            ],
        },
    ],
)


class TestContextFusionVocabularyLoader:
    """ContextFusionVocabularyLoader 基本功能测试。"""

    def test_default_constructor_loads_from_default_path(self):
        """不带参数构造时从默认路径加载。"""
        loader = ContextFusionVocabularyLoader()
        assert isinstance(loader.version, str)
        assert len(loader.version) > 0
        assert isinstance(loader.description, str)

    def test_version_property(self):
        """version 属性返回版本号。"""
        path = _write_temp_cf_vocab(_STANDARD_CF_VOCAB)
        try:
            loader = ContextFusionVocabularyLoader(catalog_path=path)
            assert loader.version == "1.0.0"
        finally:
            path.unlink(missing_ok=True)

    def test_description_property(self):
        """description 属性返回描述文本。"""
        path = _write_temp_cf_vocab(_STANDARD_CF_VOCAB)
        try:
            loader = ContextFusionVocabularyLoader(catalog_path=path)
            assert "测试用" in loader.description
        finally:
            path.unlink(missing_ok=True)

    def test_as_prompt_text_returns_non_empty_string(self):
        """as_prompt_text() 返回非空字符串。"""
        path = _write_temp_cf_vocab(_STANDARD_CF_VOCAB)
        try:
            loader = ContextFusionVocabularyLoader(catalog_path=path)
            text = loader.as_prompt_text()
            assert isinstance(text, str)
            assert len(text) > 0
        finally:
            path.unlink(missing_ok=True)

    def test_as_prompt_text_contains_domain_terms(self):
        """应包含领域术语表格。"""
        path = _write_temp_cf_vocab(_STANDARD_CF_VOCAB)
        try:
            loader = ContextFusionVocabularyLoader(catalog_path=path)
            text = loader.as_prompt_text()
            assert "领域核心术语" in text
            assert "Retrieval-Augmented Generation" in text
            assert "检索增强生成" in text
        finally:
            path.unlink(missing_ok=True)

    def test_as_prompt_text_contains_acronym_map(self):
        """应包含缩写映射表格。"""
        path = _write_temp_cf_vocab(_STANDARD_CF_VOCAB)
        try:
            loader = ContextFusionVocabularyLoader(catalog_path=path)
            text = loader.as_prompt_text()
            assert "缩写→全称映射" in text
            assert "RAG" in text
            assert "Large Language Model" in text
        finally:
            path.unlink(missing_ok=True)

    def test_as_prompt_text_contains_synonym_groups(self):
        """应包含同义表达组。"""
        path = _write_temp_cf_vocab(_STANDARD_CF_VOCAB)
        try:
            loader = ContextFusionVocabularyLoader(catalog_path=path)
            text = loader.as_prompt_text()
            assert "同义表达组" in text
            assert "搜索/检索" in text
        finally:
            path.unlink(missing_ok=True)

    def test_as_prompt_text_contains_disambiguation(self):
        """应包含上下文消歧规则。"""
        path = _write_temp_cf_vocab(_STANDARD_CF_VOCAB)
        try:
            loader = ContextFusionVocabularyLoader(catalog_path=path)
            text = loader.as_prompt_text()
            assert "上下文消歧规则" in text
            assert "RAG" in text
            assert "Retrieval-Augmented Generation" in text
        finally:
            path.unlink(missing_ok=True)

    def test_as_prompt_text_empty_catalog(self):
        """空词汇表仍正常生成文本。"""
        empty = _build_cf_vocabulary_yaml()
        path = _write_temp_cf_vocab(empty)
        try:
            loader = ContextFusionVocabularyLoader(catalog_path=path)
            text = loader.as_prompt_text()
            assert isinstance(text, str)
        finally:
            path.unlink(missing_ok=True)

    def test_custom_path_as_string(self):
        """catalog_path 接受字符串路径。"""
        path_str = str(_write_temp_cf_vocab(_STANDARD_CF_VOCAB))
        try:
            loader = ContextFusionVocabularyLoader(catalog_path=path_str)
            assert loader.version == "1.0.0"
        finally:
            Path(path_str).unlink(missing_ok=True)


class TestContextFusionVocabularyLoaderErrors:
    """ContextFusionVocabularyLoader 错误处理测试。"""

    def test_file_not_found_raises(self):
        """文件不存在时抛出 FileNotFoundError。"""
        with pytest.raises(FileNotFoundError, match="not found"):
            ContextFusionVocabularyLoader(catalog_path="/nonexistent/cf_vocab.yaml")

    def test_invalid_yaml_raises(self):
        """无效 YAML 文件抛出 yaml.YAMLError。"""
        invalid = 'version: "1.0"\ndomain_terms:\n  - : : invalid:\n'
        path = _write_temp_cf_vocab(invalid)
        try:
            with pytest.raises(yaml.YAMLError):
                ContextFusionVocabularyLoader(catalog_path=path)
        finally:
            path.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# PromptLoader 词汇表注入测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestPromptLoaderVocabularyInjection:
    """PromptLoader.load() 的词汇表注入 ({vocabulary}) 测试。"""

    def test_vocabulary_is_injected_when_provided(self):
        """提供 vocabulary 参数时，{vocabulary} 被替换为提供的文本。"""
        vocab_text = "## 测试词汇表\n这是注入的词汇表内容"
        prompts = {
            "normalize": {
                "version": "1.0.0",
                "description": "test",
                "template": "规则参考：\n{vocabulary}\n\n查询：{query}",
            },
        }
        yaml_content = _build_catalog(prompts=prompts)
        path = _write_temp_catalog(yaml_content)
        try:
            loader = PromptLoader(catalog_path=path)
            template = loader.load("normalize", vocabulary=vocab_text)
            assert vocab_text in template
            assert "{vocabulary}" not in template
        finally:
            path.unlink(missing_ok=True)

    def test_vocabulary_empty_when_not_provided(self):
        """未提供 vocabulary 时，{vocabulary} 被替换为空字符串。"""
        prompts = {
            "normalize": {
                "version": "1.0.0",
                "description": "test",
                "template": "规则参考：\n{vocabulary}\n\n查询：{query}",
            },
        }
        yaml_content = _build_catalog(prompts=prompts)
        path = _write_temp_catalog(yaml_content)
        try:
            loader = PromptLoader(catalog_path=path)
            template = loader.load("normalize")
            assert "{vocabulary}" not in template
            # 其他占位符应保留
            assert "{query}" in template
        finally:
            path.unlink(missing_ok=True)

    def test_vocabulary_with_code_default(self):
        """代码默认模板中的 {vocabulary} 也能被注入。"""
        # 代码默认模板不含 {vocabulary}，所以注入不影响
        loader = PromptLoader(catalog_path=Path("/nonexistent/path.yaml"))
        template = loader.load("context_fusion", vocabulary="test vocab")
        assert isinstance(template, str)
        assert len(template) > 0

    def test_vocabulary_with_env_var_override(self, monkeypatch):
        """环境变量中的 {vocabulary} 也能被注入。"""
        env_value = "环境变量模板 {vocabulary} {query}"
        monkeypatch.setenv("QUERY_REWRITE_PROMPT_NORMALIZE", env_value)
        loader = PromptLoader(catalog_path=Path("/nonexistent/path.yaml"))
        template = loader.load("normalize", vocabulary="注入的词汇表")
        assert "注入的词汇表" in template
        assert "{vocabulary}" not in template

    def test_no_vocabulary_placeholder_no_effect(self):
        """模板不包含 {vocabulary} 时 provide vocabulary 不影响输出。"""
        prompts = {
            "normalize": {
                "version": "1.0.0",
                "description": "test",
                "template": "查询：{query}\n保护词：{protected_terms}",
            },
        }
        yaml_content = _build_catalog(prompts=prompts)
        path = _write_temp_catalog(yaml_content)
        try:
            loader = PromptLoader(catalog_path=path)
            template = loader.load("normalize", vocabulary="should not appear")
            assert "should not appear" not in template
            assert "{query}" in template
        finally:
            path.unlink(missing_ok=True)
