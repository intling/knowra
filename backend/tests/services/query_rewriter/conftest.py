"""Shared test fixtures for query_rewriter tests.

Provides mock adapters and sample data used across all query rewriter test modules.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# ── mock_chat_adapter ─────────────────────────────────────────────────────


@pytest.fixture
def mock_chat_adapter() -> MagicMock:
    """A ChatAdapter mock that returns a controllable LLM response.

    Default behaviour:
    - ``generate()`` returns a ChatResult with content ``"这是一个改写后的查询"``
      and model ``"test-rewrite-model"``.

    Tests can override the return value per-case via
    ``mock_chat_adapter.generate.return_value = ...``.
    """
    from app.services.chat_adapter import ChatResult

    adapter = MagicMock()
    adapter.config = SimpleNamespace(
        model="test-rewrite-model",
        temperature=0.1,
        max_tokens=512,
    )
    adapter.generate = MagicMock(
        return_value=ChatResult(
            content="这是一个改写后的查询",
            model="test-rewrite-model",
            prompt_tokens=50,
            completion_tokens=20,
            total_tokens=70,
        )
    )
    return adapter


# ── mock_embedding_adapter ────────────────────────────────────────────────


@pytest.fixture
def mock_embedding_adapter() -> MagicMock:
    """An EmbeddingAdapter mock that returns a fixed 4-d vector.

    Tests can override the return value per-case via
    ``mock_embedding_adapter.embed_single.return_value = ...``.
    """
    from app.services.embedding_adapter import EmbeddingResult

    adapter = MagicMock()
    adapter.config = SimpleNamespace(
        model="test-embed-model",
        dimensions=4,
    )
    adapter.embed_single = MagicMock(
        return_value=EmbeddingResult(
            index=0,
            embedding=[0.1, 0.2, 0.3, 0.4],
            token_count=10,
        )
    )
    return adapter


# ── sample_rewrite_result ─────────────────────────────────────────────────


@pytest.fixture
def sample_rewrite_result() -> dict:
    """A sample RewriteResult-like dict used as a shared test fixture.

    Contains the fields expected in a complete rewrite result:
    original_query, rewritten_queries (list of {query, strategy}),
    strategies_used, rewrite_time_ms, cache_hit, and rewrite_model.
    """
    return {
        "original_query": "它怎么用",
        "rewritten_queries": [
            {"query": "Python 怎么使用", "strategy": "context_fusion"},
            {"query": "Python 如何使用", "strategy": "normalize"},
        ],
        "strategies_used": ["context_fusion", "normalize"],
        "rewrite_time_ms": 45.2,
        "cache_hit": False,
        "rewrite_model": None,
    }
