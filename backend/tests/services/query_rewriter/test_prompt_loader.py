"""提示词加载器测试 —— 从 YAML 文件加载策略提示词。

Phase 1 当前仅上线 context_fusion 提示词，后续 Phase 2 策略追加后扩展此测试文件。

测试覆盖：
- 正常路径：加载 context_fusion 提示词、所有注册提示词均可加载
- 错误处理：未知策略名、缺失文件、无效 YAML
- 缓存行为：同一策略多次调用返回相同对象（LRU 缓存）
- ContextRewriter 集成：默认从 YAML 加载、自定义提示词覆盖
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from app.services.prompt_loader import (
    _STRATEGY_FILE_MAP,
    get_prompts_dir,
    list_available_prompts,
    load_prompt,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 正常路径测试
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
        with patch.dict(_STRATEGY_FILE_MAP, {"test_missing": "nonexistent.yaml"}, clear=False):
            with pytest.raises(FileNotFoundError, match="Prompt file not found"):
                load_prompt("test_missing")

    def test_invalid_yaml_raises_yaml_error(self):
        """无效 YAML 文件应抛出 yaml.YAMLError。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_file = Path(tmpdir) / "bad.yaml"
            bad_file.write_text(": invalid: yaml: : :", encoding="utf-8")

            with patch.object(
                __import__("app.services.prompt_loader", fromlist=["_PROMPTS_DIR"]),
                "_PROMPTS_DIR",
                Path(tmpdir),
            ):
                with patch.dict(
                    _STRATEGY_FILE_MAP, {"test_bad_yaml": "bad.yaml"}, clear=False
                ):
                    with pytest.raises(yaml.YAMLError):
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
    """验证 ContextRewriter 与 prompt_loader 的集成。"""

    def test_context_rewriter_loads_default_prompt_from_yaml(self):
        """不带自定义提示词构造时，应从 YAML 文件加载默认提示词。"""
        from unittest.mock import MagicMock

        from app.services.context_rewriter import ContextRewriter

        mock_adapter = MagicMock()
        cr = ContextRewriter(chat_adapter=mock_adapter)

        assert len(cr._system_prompt) > 0
        assert "{history}" in cr._user_template
        assert "{query}" in cr._user_template

    def test_context_rewriter_custom_prompt_overrides_yaml(self):
        """传入自定义提示词时，应覆盖 YAML 中的默认提示词。"""
        from unittest.mock import MagicMock

        from app.services.context_rewriter import ContextRewriter

        mock_adapter = MagicMock()
        custom_system = "Custom system prompt for testing"
        custom_user = "Custom user template: {query}"

        cr = ContextRewriter(
            chat_adapter=mock_adapter,
            system_prompt=custom_system,
            user_template=custom_user,
        )

        assert cr._system_prompt == custom_system
        assert cr._user_template == custom_user


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
