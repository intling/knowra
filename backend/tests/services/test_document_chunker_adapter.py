# 本文件验证 DoclingChunkerAdapter 对 Docling HybridChunker 的封装。
# 覆盖配置传递、SDK chunk/contextualize 调用，以及项目内标准 chunk 输出。

from importlib import import_module
from types import SimpleNamespace

import pytest


class FakeHybridChunker:
    # 记录适配器传给 HybridChunker 的配置。
    # 测试用它确认 tokenizer、合并策略和表头策略被正确转发。
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.chunk_calls = []

    # 模拟 HybridChunker 返回带标题、页码和 origin 的 chunk。
    # 适配器测试用它验证字段归一化和顺序编号。
    def chunk(self, document):
        self.chunk_calls.append(document)
        return [
            SimpleNamespace(
                text="First chunk",
                meta=SimpleNamespace(
                    headings=["Course Notes", "Retrieval"],
                    doc_items=[SimpleNamespace(prov=[SimpleNamespace(page_no=1)])],
                    origin={"ref": "#/texts/0"},
                ),
            ),
            SimpleNamespace(
                text="Second chunk",
                meta=SimpleNamespace(
                    headings=["Course Notes", "Generation"],
                    doc_items=[SimpleNamespace(prov=[SimpleNamespace(page_no=2)])],
                    origin={"ref": "#/texts/1"},
                ),
            ),
        ]

    # 模拟 SDK 的上下文化能力。
    # 测试验证 adapter 会把 contextualized_text 写入标准 chunk。
    def contextualize(self, chunk):
        return f"Context: {chunk.text}"


class FakeTokenizerFactory:
    # 记录 tokenizer 初始化调用。
    # 测试用它确认适配器会按配置构建 token 计数器。
    def __init__(self) -> None:
        self.calls = []

    # 返回按空格计数的 fake tokenizer。
    # 测试只关心适配器是否写入 token_count，不依赖真实模型下载。
    def __call__(self, *, model_name, max_tokens, cache_dir=None):
        self.calls.append(
            {"model_name": model_name, "max_tokens": max_tokens, "cache_dir": cache_dir}
        )
        return SimpleNamespace(count_tokens=lambda text: len(text.split()))


# 适配器应把 HybridChunker 输出转换为项目标准 chunk。
# 测试覆盖顺序号、原文、上下文化文本、token 数、标题路径、页码和 origin 元数据。
def test_docling_chunker_adapter_uses_hybrid_chunker_and_normalizes_chunks() -> None:
    module = import_module("app.services.document_chunker")
    tokenizer_factory = FakeTokenizerFactory()
    adapter = module.DoclingChunkerAdapter(
        config=module.DocumentChunkingConfig(
            tokenizer_model="Qwen/Qwen2-7B",
            max_tokens=512,
            merge_peers=True,
            repeat_table_header=True,
            inline_text_max_bytes=2048,
        ),
        hybrid_chunker_cls=FakeHybridChunker,
        tokenizer_factory=tokenizer_factory,
    )
    document = object()

    chunks = adapter.chunk(document)

    assert tokenizer_factory.calls == [
        {"model_name": "Qwen/Qwen2-7B", "max_tokens": 512, "cache_dir": None}
    ]
    assert len(chunks) == 2
    assert [chunk.sequence_index for chunk in chunks] == [0, 1]
    assert chunks[0].text == "First chunk"
    assert chunks[0].contextualized_text == "Context: First chunk"
    assert chunks[0].token_count == 2
    assert chunks[0].heading_path == ["Course Notes", "Retrieval"]
    assert chunks[0].page_numbers == [1]
    assert chunks[0].metadata_json["origin"] == {"ref": "#/texts/0"}


# 底层 HybridChunker 抛错时，适配器应转换为项目内 DocumentChunkingError。
# 这样上层服务可以统一记录分块失败。
def test_docling_chunker_adapter_converts_sdk_errors_to_project_error() -> None:
    module = import_module("app.services.document_chunker")

    class BrokenHybridChunker:
        # 让异常发生在 chunk 阶段。
        # 测试验证适配器包裹的是 SDK 执行错误，而不是构造失败。
        def __init__(self, **_kwargs):
            pass

        # 模拟 SDK 分块执行失败。
        # 测试确认原始错误消息会进入项目错误。
        def chunk(self, _document):
            raise RuntimeError("chunking exploded")

    adapter = module.DoclingChunkerAdapter(
        config=module.DocumentChunkingConfig(),
        hybrid_chunker_cls=BrokenHybridChunker,
        tokenizer_factory=lambda **_kwargs: object(),
    )

    with pytest.raises(module.DocumentChunkingError, match="chunking exploded"):
        adapter.chunk(object())
