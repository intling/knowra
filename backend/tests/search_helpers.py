"""搜索端到端测试的共享辅助函数。

为 ``test_search_route_rewrite.py`` 和 ``test_query_rewrite_e2e.py``
提供可复用的 fake 对象构建器，消除重复代码。
"""

from __future__ import annotations

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4


def make_fake_embedding_adapter(
    *,
    vector_dims: int = 2560,
    model: str = "test-embed-model",
    raise_error: Exception | None = None,
):
    """Create a fake EmbeddingAdapter."""
    adapter = MagicMock()
    adapter.config = SimpleNamespace(model=model, dimensions=vector_dims)
    if raise_error:
        adapter.embed_single = MagicMock(side_effect=raise_error)
    else:
        result = SimpleNamespace(embedding=[0.1] * vector_dims)
        adapter.embed_single = MagicMock(return_value=result)
    return adapter


def make_fake_chat_adapter(*, content: str = "AI 生成的回答。", model: str = "test-chat-model"):
    """Create a fake ChatAdapter.

    ``generate_async`` is an ``AsyncMock`` — awaitable and supports call assertions.
    ``generate`` is a sync ``MagicMock`` for backward-compatible test paths.
    """
    chat_module = import_module("app.services.chat_adapter")
    adapter = MagicMock()
    adapter.config = SimpleNamespace(model=model)
    adapter.generate = MagicMock(
        return_value=chat_module.ChatResult(
            content=content,
            model=model,
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
    )
    adapter.generate_async = AsyncMock(
        return_value=chat_module.ChatResult(
            content=content,
            model=model,
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
    )
    return adapter


def make_fake_chat_config(*, model: str = "test-chat-model", **overrides):
    """Build a fake ChatConfig."""
    defaults = {
        "api_base_url": "https://test-api.example.com/v1",
        "api_key": "sk-test-key",
        "model": model,
        "temperature": 0.1,
        "max_tokens": 1024,
        "request_timeout": 30.0,
        "max_retries": 3,
        "first_token_timeout": 10.0,
    }
    defaults.update(overrides)
    chat_config_module = import_module("app.services.chat_config")
    return chat_config_module.ChatConfig(**defaults)


def make_fake_session(*, total_embedding_count: int = 1, rows: list | None = None):
    """Create a fake SQLModel Session for the search query."""
    session = MagicMock()
    if rows is None:
        rows = []
    mock_result = MagicMock()
    mock_result.all.return_value = rows
    mock_result.scalar.return_value = total_embedding_count
    session.exec.return_value = mock_result
    return session


def make_fake_db_row(
    *,
    rank: int = 1,
    score: float = 0.123,
    chunk_id: UUID | None = None,
    parsed_document_id: UUID | None = None,
    document_name: str = "test-doc.pdf",
    sequence_index: int = 1,
    text: str = "这是测试分块文本内容。",
    contextualized_text: str = "上下文增强的测试分块文本。",
    token_count: int = 50,
    heading_path: list[str] | None = None,
    page_numbers: list[int] | None = None,
):
    """Create a fake DB row matching the pgvector JOIN query shape."""
    chunk_id = chunk_id or uuid4()
    parsed_doc_id = parsed_document_id or uuid4()

    embedding = SimpleNamespace(
        id=uuid4(),
        chunk_id=chunk_id,
        parsed_document_id=parsed_doc_id,
        sequence_index=sequence_index,
        model="test-embed-model",
        dimensions=2560,
    )
    chunk = SimpleNamespace(
        id=chunk_id,
        parsed_document_id=parsed_doc_id,
        sequence_index=sequence_index,
        text=text,
        contextualized_text=contextualized_text,
        token_count=token_count,
        heading_path=heading_path or ["第一章", "第一节"],
        page_numbers=page_numbers or [1, 2],
    )
    parsed_doc = SimpleNamespace(id=parsed_doc_id)

    return SimpleNamespace(
        DocumentEmbedding=embedding,
        DocumentChunk=chunk,
        ParsedDocument=parsed_doc,
        document_name=document_name,
        score=score,
    )
