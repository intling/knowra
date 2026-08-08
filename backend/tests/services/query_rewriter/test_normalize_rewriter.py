"""NormalizeRewriter 测试 —— 查询规范化重述策略。

测试覆盖：
- 正常路径：口语化查询 → 规范书面语（口语转书面、错别字修正、冗余词去除）
- 边界情况：已是规范查询时保持原样、纯符号/数字查询原样返回、空字符串处理
- LLM 调用失败降级：返回原始查询
- Prompt 模板占位符正确填充：{query}、{protected_terms}

.. note::
    本文件为 Phase 2 的**红测试**（TDD Red Phase）。
    NormalizeRewriter 尚未实现，运行时应预期失败。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.chat_adapter import ChatAPIError, ChatResult

# ── 共享 fixture ──────────────────────────────────────────────────────────


@pytest.fixture
def mock_prompt_loader() -> MagicMock:
    """Mock PromptLoader —— 模拟三层降级加载器行为。

    使用 ``side_effect`` 正确模拟 ``PromptLoader.load("normalize", vocabulary=...)``
    的契约：当传入 ``vocabulary`` 参数时，返回的模板中 ``{vocabulary}`` 已被替换。
    """
    _TEMPLATE = (
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
    )

    def _load_side_effect(strategy_name: str, *, vocabulary: str = "") -> str:
        """模拟 PromptLoader.load() 的词汇表注入行为。"""
        assert strategy_name == "normalize", f"Unexpected strategy: {strategy_name}"
        return _TEMPLATE.replace("{vocabulary}", vocabulary)

    loader = MagicMock()
    loader.load.side_effect = _load_side_effect
    return loader


@pytest.fixture
def mock_chat_adapter_normalize() -> MagicMock:
    """ChatAdapter mock for NormalizeRewriter tests —— 默认返回规范化查询。"""
    from types import SimpleNamespace

    adapter = MagicMock()
    adapter.config = SimpleNamespace(
        model="test-rewrite-model",
        temperature=0.1,
        max_tokens=512,
    )
    adapter.generate.return_value = ChatResult(
        content="如何学习 Python",
        model="test-rewrite-model",
        prompt_tokens=80,
        completion_tokens=15,
        total_tokens=95,
    )
    return adapter


# ── 辅助：构建待测 NormalizeRewriter ─────────────────────────────────────

# NormalizeRewriter 类将在 7.2.0 实现，暂定接口：
#   NormalizeRewriter(chat_adapter, prompt_loader)
#   async rewrite(query, protected_terms=None) -> dict
#       dict keys: query, strategy, duration_ms, tokens

_NORMALIZE_REWRITER_MODULE = "app.services.normalize_rewriter"


def _build_rewriter(chat_adapter=None, prompt_loader=None):
    """构建 NormalizeRewriter 实例。"""
    from app.services.normalize_rewriter import NormalizeRewriter  # noqa: F401

    return NormalizeRewriter(
        chat_adapter=chat_adapter or MagicMock(),
        prompt_loader=prompt_loader or MagicMock(),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 正常路径测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestNormalizeRewriterNormalPath:
    """验证口语化查询 → 规范书面语的核心路径。"""

    @pytest.mark.asyncio
    async def test_colloquial_to_formal(self, mock_chat_adapter_normalize, mock_prompt_loader):
        """口语化查询应被改写为规范书面语。

        例："咋整Python" → "如何学习Python"
        """
        mock_chat_adapter_normalize.generate.return_value = ChatResult(
            content="如何学习 Python",
            model="test-rewrite-model",
            prompt_tokens=80,
            completion_tokens=15,
            total_tokens=95,
        )

        rewriter = _build_rewriter(
            chat_adapter=mock_chat_adapter_normalize,
            prompt_loader=mock_prompt_loader,
        )
        result = await rewriter.rewrite("咋整Python")

        assert result["query"] == "如何学习 Python"
        assert result["strategy"] == "normalize"
        assert result["duration_ms"] > 0
        assert result["tokens"] > 0

    @pytest.mark.asyncio
    async def test_typo_correction(self, mock_chat_adapter_normalize, mock_prompt_loader):
        """错别字应被修正。

        例："布署到服务器" → "部署到服务器"
        """
        mock_chat_adapter_normalize.generate.return_value = ChatResult(
            content="部署到服务器",
            model="test-rewrite-model",
            prompt_tokens=70,
            completion_tokens=10,
            total_tokens=80,
        )

        rewriter = _build_rewriter(
            chat_adapter=mock_chat_adapter_normalize,
            prompt_loader=mock_prompt_loader,
        )
        result = await rewriter.rewrite("布署到服务器")

        assert result["query"] == "部署到服务器"
        assert result["strategy"] == "normalize"

    @pytest.mark.asyncio
    async def test_redundancy_removal(self, mock_chat_adapter_normalize, mock_prompt_loader):
        """冗余词/语气填充词应被去除。

        例："嗯 那个 怎么配置 nginx 啊" → "如何配置 Nginx"
        """
        mock_chat_adapter_normalize.generate.return_value = ChatResult(
            content="如何配置 Nginx",
            model="test-rewrite-model",
            prompt_tokens=90,
            completion_tokens=12,
            total_tokens=102,
        )

        rewriter = _build_rewriter(
            chat_adapter=mock_chat_adapter_normalize,
            prompt_loader=mock_prompt_loader,
        )
        result = await rewriter.rewrite("嗯 那个 怎么配置 nginx 啊")

        assert result["query"] == "如何配置 Nginx"
        assert result["strategy"] == "normalize"

    @pytest.mark.asyncio
    async def test_combined_normalization(self, mock_chat_adapter_normalize, mock_prompt_loader):
        """口语化+错别字+冗余词应被综合处理。

        例："就是说 那个 程系 老是 报错，帮我看看 咋回事 呗"
        → "程序频繁报错，请查看原因"
        """
        mock_chat_adapter_normalize.generate.return_value = ChatResult(
            content="程序频繁报错，请查看原因",
            model="test-rewrite-model",
            prompt_tokens=120,
            completion_tokens=25,
            total_tokens=145,
        )

        rewriter = _build_rewriter(
            chat_adapter=mock_chat_adapter_normalize,
            prompt_loader=mock_prompt_loader,
        )
        result = await rewriter.rewrite("就是说 那个 程系 老是 报错，帮我看看 咋回事 呗")

        assert result["query"] == "程序频繁报错，请查看原因"
        assert result["strategy"] == "normalize"

    @pytest.mark.asyncio
    async def test_duration_ms_tracked(self, mock_chat_adapter_normalize, mock_prompt_loader):
        """每次调用应追踪执行耗时（duration_ms）。"""
        rewriter = _build_rewriter(
            chat_adapter=mock_chat_adapter_normalize,
            prompt_loader=mock_prompt_loader,
        )
        result = await rewriter.rewrite("测试查询")

        assert "duration_ms" in result
        assert isinstance(result["duration_ms"], (int, float))
        assert result["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_tokens_tracked(self, mock_chat_adapter_normalize, mock_prompt_loader):
        """每次调用应追踪 token 消耗。"""
        rewriter = _build_rewriter(
            chat_adapter=mock_chat_adapter_normalize,
            prompt_loader=mock_prompt_loader,
        )
        result = await rewriter.rewrite("测试查询")

        assert "tokens" in result
        assert isinstance(result["tokens"], int)
        # 验证 tokens 与 mock_chat_adapter_normalize fixture 中 ChatResult 的 total_tokens 一致
        assert result["tokens"] == 95


# ═══════════════════════════════════════════════════════════════════════════════
# 边界情况测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestNormalizeRewriterEdgeCases:
    """验证边界情况下的行为。"""

    @pytest.mark.asyncio
    async def test_already_normalized_query_unchanged(
        self, mock_chat_adapter_normalize, mock_prompt_loader
    ):
        """已经是规范书面语的查询应保持原样。

        LLM 可能返回完全相同的文本或微小调整，测试验证结果非空且合理。
        """
        already_normal = "如何配置 Nginx 反向代理"
        mock_chat_adapter_normalize.generate.return_value = ChatResult(
            content=already_normal,
            model="test-rewrite-model",
            prompt_tokens=60,
            completion_tokens=12,
            total_tokens=72,
        )

        rewriter = _build_rewriter(
            chat_adapter=mock_chat_adapter_normalize,
            prompt_loader=mock_prompt_loader,
        )
        result = await rewriter.rewrite(already_normal)

        # 结果应非空，且与输入基本一致（或就是原样返回）
        assert result["query"]
        assert result["strategy"] == "normalize"

    @pytest.mark.asyncio
    async def test_pure_symbols_unchanged(self, mock_chat_adapter_normalize, mock_prompt_loader):
        """纯符号/数字查询应原样返回。"""
        pure_symbols = "12345 !@#$%"
        mock_chat_adapter_normalize.generate.return_value = ChatResult(
            content=pure_symbols,
            model="test-rewrite-model",
            prompt_tokens=30,
            completion_tokens=8,
            total_tokens=38,
        )

        rewriter = _build_rewriter(
            chat_adapter=mock_chat_adapter_normalize,
            prompt_loader=mock_prompt_loader,
        )
        result = await rewriter.rewrite(pure_symbols)

        assert result["query"]
        assert result["strategy"] == "normalize"

    @pytest.mark.asyncio
    async def test_numeric_query_unchanged(self, mock_chat_adapter_normalize, mock_prompt_loader):
        """纯数字查询应原样返回。"""
        numeric_query = "3.10.0 8080 443"
        mock_chat_adapter_normalize.generate.return_value = ChatResult(
            content=numeric_query,
            model="test-rewrite-model",
            prompt_tokens=25,
            completion_tokens=8,
            total_tokens=33,
        )

        rewriter = _build_rewriter(
            chat_adapter=mock_chat_adapter_normalize,
            prompt_loader=mock_prompt_loader,
        )
        result = await rewriter.rewrite(numeric_query)

        assert result["query"]
        assert result["strategy"] == "normalize"

    @pytest.mark.asyncio
    async def test_empty_string_handling(self, mock_chat_adapter_normalize, mock_prompt_loader):
        """空字符串查询应能正常处理（不崩溃）。

        可能的行为：返回空字符串或原始空字符串。
        """
        mock_chat_adapter_normalize.generate.return_value = ChatResult(
            content="",
            model="test-rewrite-model",
            prompt_tokens=10,
            completion_tokens=0,
            total_tokens=10,
        )

        rewriter = _build_rewriter(
            chat_adapter=mock_chat_adapter_normalize,
            prompt_loader=mock_prompt_loader,
        )
        # 不应抛出异常
        result = await rewriter.rewrite("")

        assert "query" in result
        assert result["strategy"] == "normalize"

    @pytest.mark.asyncio
    async def test_short_query(self, mock_chat_adapter_normalize, mock_prompt_loader):
        """非常短的查询（如单字）应正常处理。"""
        short_query = "报"
        mock_chat_adapter_normalize.generate.return_value = ChatResult(
            content="报错信息",
            model="test-rewrite-model",
            prompt_tokens=30,
            completion_tokens=5,
            total_tokens=35,
        )

        rewriter = _build_rewriter(
            chat_adapter=mock_chat_adapter_normalize,
            prompt_loader=mock_prompt_loader,
        )
        result = await rewriter.rewrite(short_query)

        assert result["query"]
        assert result["strategy"] == "normalize"

    @pytest.mark.asyncio
    async def test_english_query_normalized(self, mock_chat_adapter_normalize, mock_prompt_loader):
        """英文查询中的非规范表达应被修正。

        例："how 2 learn python" → "How to learn Python"
        """
        mock_chat_adapter_normalize.generate.return_value = ChatResult(
            content="How to learn Python",
            model="test-rewrite-model",
            prompt_tokens=50,
            completion_tokens=10,
            total_tokens=60,
        )

        rewriter = _build_rewriter(
            chat_adapter=mock_chat_adapter_normalize,
            prompt_loader=mock_prompt_loader,
        )
        result = await rewriter.rewrite("how 2 learn python")

        assert result["query"] == "How to learn Python"
        assert result["strategy"] == "normalize"

    @pytest.mark.asyncio
    async def test_query_with_code_blocks_preserved(
        self, mock_chat_adapter_normalize, mock_prompt_loader
    ):
        """含代码片段的查询中，代码部分应保持原样。"""
        query_with_code = "这个 `docker run -p 8080:80` 咋用"
        mock_chat_adapter_normalize.generate.return_value = ChatResult(
            content="如何使用 `docker run -p 8080:80`",
            model="test-rewrite-model",
            prompt_tokens=70,
            completion_tokens=15,
            total_tokens=85,
        )

        rewriter = _build_rewriter(
            chat_adapter=mock_chat_adapter_normalize,
            prompt_loader=mock_prompt_loader,
        )
        result = await rewriter.rewrite(query_with_code)

        # 代码片段应被保留在输出中
        assert "docker run -p 8080:80" in result["query"]
        assert result["strategy"] == "normalize"


# ═══════════════════════════════════════════════════════════════════════════════
# LLM 调用失败降级测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestNormalizeRewriterFallback:
    """验证 LLM 调用失败时的降级行为。"""

    @pytest.mark.asyncio
    async def test_llm_failure_returns_original_query(
        self, mock_chat_adapter_normalize, mock_prompt_loader
    ):
        """LLM 调用抛出 ChatAPIError 时应返回原始查询，不抛出异常。"""
        mock_chat_adapter_normalize.generate.side_effect = ChatAPIError("API 调用失败")

        rewriter = _build_rewriter(
            chat_adapter=mock_chat_adapter_normalize,
            prompt_loader=mock_prompt_loader,
        )
        original = "咋整Python"
        result = await rewriter.rewrite(original)

        # 降级：返回原始查询
        assert result["query"] == original
        assert result["strategy"] == "normalize"
        # 降级时 duration_ms 仍应被记录
        assert "duration_ms" in result

    @pytest.mark.asyncio
    async def test_llm_failure_still_returns_strategy_label(
        self, mock_chat_adapter_normalize, mock_prompt_loader
    ):
        """LLM 失败降级时 strategy 字段仍应为 "normalize"。"""
        mock_chat_adapter_normalize.generate.side_effect = ChatAPIError("超时")

        rewriter = _build_rewriter(
            chat_adapter=mock_chat_adapter_normalize,
            prompt_loader=mock_prompt_loader,
        )
        result = await rewriter.rewrite("测试查询")

        assert result["strategy"] == "normalize"

    @pytest.mark.asyncio
    async def test_llm_failure_tokens_zero(self, mock_chat_adapter_normalize, mock_prompt_loader):
        """LLM 失败降级时 tokens 应为 0（未实际消耗）。"""
        mock_chat_adapter_normalize.generate.side_effect = ChatAPIError("连接失败")

        rewriter = _build_rewriter(
            chat_adapter=mock_chat_adapter_normalize,
            prompt_loader=mock_prompt_loader,
        )
        result = await rewriter.rewrite("测试查询")

        assert result["tokens"] == 0

    @pytest.mark.asyncio
    async def test_llm_returns_empty_content(self, mock_chat_adapter_normalize, mock_prompt_loader):
        """LLM 返回空内容时应返回原始查询作为安全兜底。"""
        mock_chat_adapter_normalize.generate.return_value = ChatResult(
            content="",  # LLM 返回空内容
            model="test-rewrite-model",
            prompt_tokens=50,
            completion_tokens=0,
            total_tokens=50,
        )

        rewriter = _build_rewriter(
            chat_adapter=mock_chat_adapter_normalize,
            prompt_loader=mock_prompt_loader,
        )
        original = "怎么配置"
        result = await rewriter.rewrite(original)

        # 空内容应降级为原始查询
        assert result["query"] == original
        assert result["strategy"] == "normalize"


# ═══════════════════════════════════════════════════════════════════════════════
# Prompt 模板占位符正确填充测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestNormalizeRewriterPromptFilling:
    """验证 Prompt 模板中 {query} 和 {protected_terms} 占位符被正确填充。"""

    @pytest.mark.asyncio
    async def test_query_placeholder_filled(self, mock_chat_adapter_normalize, mock_prompt_loader):
        """Prompt 模板中的 {query} 应被替换为实际查询文本。"""
        rewriter = _build_rewriter(
            chat_adapter=mock_chat_adapter_normalize,
            prompt_loader=mock_prompt_loader,
        )
        await rewriter.rewrite("测试查询")

        # 验证 PromptLoader.load 被调用（用于获取模板）
        mock_prompt_loader.load.assert_called_once()
        # 验证 ChatAdapter.generate 被调用，且 messages 中包含查询文本
        mock_chat_adapter_normalize.generate.assert_called_once()
        call_args = mock_chat_adapter_normalize.generate.call_args
        messages = call_args[0][0] if call_args[0] else call_args[1].get("messages", [])
        # 将所有消息内容拼接，检查是否包含查询文本
        all_content = " ".join(m.get("content", "") for m in messages)
        assert "测试查询" in all_content

    @pytest.mark.asyncio
    async def test_protected_terms_placeholder_filled(
        self, mock_chat_adapter_normalize, mock_prompt_loader
    ):
        """Prompt 模板中的 {protected_terms} 应被替换为保护词列表。"""
        rewriter = _build_rewriter(
            chat_adapter=mock_chat_adapter_normalize,
            prompt_loader=mock_prompt_loader,
        )
        protected = ["__TERM1__", "__TERM2__"]
        await rewriter.rewrite("查询 __TERM1__ 的用法", protected_terms=protected)

        # 验证 ChatAdapter.generate 的 messages 中包含保护词
        mock_chat_adapter_normalize.generate.assert_called_once()
        call_args = mock_chat_adapter_normalize.generate.call_args
        messages = call_args[0][0] if call_args[0] else call_args[1].get("messages", [])
        all_content = " ".join(m.get("content", "") for m in messages)
        assert "__TERM1__" in all_content
        assert "__TERM2__" in all_content

    @pytest.mark.asyncio
    async def test_protected_terms_none_handled(
        self, mock_chat_adapter_normalize, mock_prompt_loader
    ):
        """protected_terms=None 时应正常处理（不崩溃），模板中保护词区域为空。"""
        rewriter = _build_rewriter(
            chat_adapter=mock_chat_adapter_normalize,
            prompt_loader=mock_prompt_loader,
        )
        # protected_terms 不传或传 None
        result = await rewriter.rewrite("正常查询")

        assert result["strategy"] == "normalize"
        # 不应崩溃
        mock_chat_adapter_normalize.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_protected_terms_empty_list_handled(
        self, mock_chat_adapter_normalize, mock_prompt_loader
    ):
        """protected_terms=[] 空列表时应正常处理。"""
        rewriter = _build_rewriter(
            chat_adapter=mock_chat_adapter_normalize,
            prompt_loader=mock_prompt_loader,
        )
        result = await rewriter.rewrite("正常查询", protected_terms=[])

        assert result["strategy"] == "normalize"
        mock_chat_adapter_normalize.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_prompt_loader_called_with_normalize_strategy(
        self, mock_chat_adapter_normalize, mock_prompt_loader
    ):
        """应使用 PromptLoader.load("normalize") 获取模板。"""
        from unittest.mock import ANY

        rewriter = _build_rewriter(
            chat_adapter=mock_chat_adapter_normalize,
            prompt_loader=mock_prompt_loader,
        )
        await rewriter.rewrite("任意查询")

        mock_prompt_loader.load.assert_called_with("normalize", vocabulary=ANY)

    @pytest.mark.asyncio
    async def test_vocabulary_injected_into_template(
        self, mock_chat_adapter_normalize, mock_prompt_loader
    ):
        """PromptLoader.load 应传入 vocabulary 参数以注入词汇表。"""
        rewriter = _build_rewriter(
            chat_adapter=mock_chat_adapter_normalize,
            prompt_loader=mock_prompt_loader,
        )
        await rewriter.rewrite("查询")

        # 验证 load 调用时传入了 vocabulary 参数
        call_kwargs = mock_prompt_loader.load.call_args
        assert "vocabulary" in call_kwargs[1], (
            "PromptLoader.load 应接收 vocabulary 关键字参数以注入词汇表"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 构造与依赖注入测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestNormalizeRewriterConstruction:
    """验证 NormalizeRewriter 的构造与依赖注入。"""

    def test_constructor_requires_chat_adapter(self):
        """构造 NormalizeRewriter 必须传入 chat_adapter。"""
        from app.services.normalize_rewriter import NormalizeRewriter  # noqa: F401

        with pytest.raises(TypeError):
            NormalizeRewriter(prompt_loader=MagicMock())  # type: ignore[call-arg]

    def test_constructor_requires_prompt_loader(self):
        """构造 NormalizeRewriter 必须传入 prompt_loader。"""
        from app.services.normalize_rewriter import NormalizeRewriter  # noqa: F401

        with pytest.raises(TypeError):
            NormalizeRewriter(chat_adapter=MagicMock())  # type: ignore[call-arg]

    def test_constructor_accepts_both_dependencies(self):
        """传入 chat_adapter 和 prompt_loader 应正常构造。"""
        rewriter = _build_rewriter(
            chat_adapter=MagicMock(),
            prompt_loader=MagicMock(),
        )
        assert rewriter is not None
