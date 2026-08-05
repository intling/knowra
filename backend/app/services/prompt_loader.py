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
        raise FileNotFoundError(
            f"Prompt file not found: {file_path} (strategy: {strategy_name})"
        )

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
