# 本文件验证 EmbeddingAdapter 对 OpenAI 兼容 embedding API 的封装。
# 覆盖单文本/批量向量化、超大批次拆分、重试策略、响应校验和配置工厂方法。

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# ── helpers ────────────────────────────────────────────────────────


def get_adapter_module():
    return import_module("app.services.embedding_adapter")


def get_config_module():
    return import_module("app.services.embedding_config")


def make_config(**overrides):
    """Build an EmbeddingConfig with sensible test defaults."""
    config_module = get_config_module()
    defaults = {
        "api_base_url": "https://test-api.example.com/v1",
        "api_key": "sk-test-key",
        "model": "test-model",
        "dimensions": 128,
        "encoding_format": "float",
        "batch_size": 10,
        "max_retries": 3,
        "request_timeout": 30.0,
    }
    defaults.update(overrides)
    return config_module.EmbeddingConfig(**defaults)


def make_fake_embedding_item(index: int, embedding: list[float] | None = None):
    """Create a fake OpenAI embedding response item."""
    emb = embedding if embedding is not None else [0.1 * (index + 1)] * 128
    return SimpleNamespace(index=index, embedding=emb)


def make_fake_response(items: list):
    """Create a fake OpenAI embeddings.create() response."""
    return SimpleNamespace(data=items)


def make_mock_response(status_code: int = 200):
    """Create a mock httpx.Response-like object for APIStatusError."""
    from unittest.mock import MagicMock

    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    return mock_resp


class FakeEmbeddings:
    """A fake ``client.embeddings`` that records calls and returns canned responses."""

    def __init__(self, responses=None, side_effect=None):
        self.calls: list[dict] = []
        self._responses = responses or []
        self._side_effect = side_effect
        self._call_index = 0

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._side_effect is not None:
            if isinstance(self._side_effect, list):
                result = self._side_effect[self._call_index]
                self._call_index += 1
                if isinstance(result, Exception):
                    raise result
                return result
            exc = self._side_effect
            self._call_index += 1
            if isinstance(exc, Exception):
                raise exc
            return exc
        if self._responses:
            result = self._responses[self._call_index % len(self._responses)]
            self._call_index += 1
            return result
        return make_fake_response([])


class FakeClient:
    """A fake OpenAI client whose ``embeddings`` attribute is a ``FakeEmbeddings``."""

    def __init__(self, responses=None, side_effect=None):
        self.embeddings = FakeEmbeddings(responses=responses, side_effect=side_effect)


# ── 4.1 单文本 / 批量向量化 ────────────────────────────────────────


# 单文本向量化应返回正确的 EmbeddingResult，index 为 0。
def test_embed_single_returns_correct_result():
    module = get_adapter_module()
    config = make_config(dimensions=3)
    fake_client = FakeClient(
        responses=[make_fake_response([make_fake_embedding_item(0, [1.0, 2.0, 3.0])])]
    )
    adapter = module.EmbeddingAdapter(config=config, client=fake_client)

    result = adapter.embed_single("hello")

    assert isinstance(result, module.EmbeddingResult)
    assert result.index == 0
    assert result.embedding == [1.0, 2.0, 3.0]


# 批量文本向量化应按输入顺序返回结果，每个结果 index 对应输入位置。
def test_embed_batch_returns_results_in_input_order():
    module = get_adapter_module()
    config = make_config(dimensions=2, batch_size=10)
    items = [
        make_fake_embedding_item(0, [0.1, 0.2]),
        make_fake_embedding_item(1, [0.3, 0.4]),
        make_fake_embedding_item(2, [0.5, 0.6]),
    ]
    fake_client = FakeClient(responses=[make_fake_response(items)])
    adapter = module.EmbeddingAdapter(config=config, client=fake_client)

    results = adapter.embed(["text a", "text b", "text c"])

    assert len(results) == 3
    assert results[0].index == 0
    assert results[0].embedding == [0.1, 0.2]
    assert results[1].index == 1
    assert results[1].embedding == [0.3, 0.4]
    assert results[2].index == 2
    assert results[2].embedding == [0.5, 0.6]


# ── 4.2 超大批次拆分 ──────────────────────────────────────────────


# 当输入超过 batch_size 时适配器应拆分为多个 API 调用，结果按原始顺序合并。
def test_embed_splits_exceeding_batch_size():
    module = get_adapter_module()
    config = make_config(batch_size=2, dimensions=1)

    # Each batch returns 2 items with indices 0, 1
    batch1 = make_fake_response(
        [
            make_fake_embedding_item(0, [1.0]),
            make_fake_embedding_item(1, [2.0]),
        ]
    )
    batch2 = make_fake_response(
        [
            make_fake_embedding_item(0, [3.0]),
            make_fake_embedding_item(1, [4.0]),
        ]
    )
    batch3 = make_fake_response(
        [
            make_fake_embedding_item(0, [5.0]),
        ]
    )
    fake_client = FakeClient(responses=[batch1, batch2, batch3])
    adapter = module.EmbeddingAdapter(config=config, client=fake_client)

    results = adapter.embed(["a", "b", "c", "d", "e"])

    assert len(results) == 5
    assert [r.index for r in results] == [0, 1, 2, 3, 4]
    assert [r.embedding for r in results] == [[1.0], [2.0], [3.0], [4.0], [5.0]]
    # Verify three API calls were made with correct sub-batches.
    assert len(fake_client.embeddings.calls) == 3
    assert fake_client.embeddings.calls[0]["input"] == ["a", "b"]
    assert fake_client.embeddings.calls[1]["input"] == ["c", "d"]
    assert fake_client.embeddings.calls[2]["input"] == ["e"]


# 空列表应返回空结果，不发起 API 调用。
def test_embed_empty_list_returns_empty():
    module = get_adapter_module()
    config = make_config()
    fake_client = FakeClient()
    adapter = module.EmbeddingAdapter(config=config, client=fake_client)

    results = adapter.embed([])

    assert results == []
    assert fake_client.embeddings.calls == []


# ── 4.3 网络超时重试 ──────────────────────────────────────────────


# 网络超时时适配器应自动重试，超过 max_retries 后抛出 EmbeddingAPIError。
def test_embed_retries_on_timeout_then_raises_embedding_api_error():
    module = get_adapter_module()
    adapter_module = get_adapter_module()
    config = make_config(max_retries=2, dimensions=1)

    # Simulate timeouts for every attempt.
    from openai import APITimeoutError

    timeout_error = APITimeoutError("Request timed out")
    fake_client = FakeClient(side_effect=timeout_error)
    adapter = module.EmbeddingAdapter(config=config, client=fake_client)

    with (
        patch("time.sleep", return_value=None) as mock_sleep,
        pytest.raises(adapter_module.EmbeddingAPIError, match="timed out"),
    ):
        adapter.embed_single("test")

    # max_retries=2 → attempts: 0 (initial), 1 (retry), 2 (retry) = 3 total
    # sleep is called between attempts: after attempt 0 and attempt 1 → 2 sleeps
    assert mock_sleep.call_count == 2
    assert fake_client.embeddings.calls  # Verify calls were attempted.


# ── 4.4 5xx 重试 / 4xx 立即失败 ────────────────────────────────────


# API 返回 5xx 时适配器应自动重试，重试耗尽后抛出 EmbeddingAPIError 并携带状态码。
def test_embed_retries_on_5xx():
    module = get_adapter_module()
    config = make_config(max_retries=2, dimensions=1)

    from openai import APIStatusError

    server_error = APIStatusError(
        "Internal Server Error",
        response=make_mock_response(status_code=500),
        body=None,
    )
    fake_client = FakeClient(side_effect=server_error)
    adapter = module.EmbeddingAdapter(config=config, client=fake_client)

    with (
        patch("time.sleep", return_value=None),
        pytest.raises(module.EmbeddingAPIError) as exc_info,
    ):
        adapter.embed_single("test")

    assert exc_info.value.status_code == 500
    # 3 total attempts (initial + 2 retries).
    assert len(fake_client.embeddings.calls) == 3


# API 返回 4xx（如认证失败）时适配器应立即失败不重试。
def test_embed_fails_immediately_on_4xx():
    module = get_adapter_module()
    config = make_config(max_retries=3)

    from openai import APIStatusError

    auth_error = APIStatusError(
        "Unauthorized",
        response=make_mock_response(status_code=401),
        body=None,
    )
    fake_client = FakeClient(side_effect=auth_error)
    adapter = module.EmbeddingAdapter(config=config, client=fake_client)

    with (
        patch("time.sleep", return_value=None) as mock_sleep,
        pytest.raises(module.EmbeddingAPIError) as exc_info,
    ):
        adapter.embed_single("test")

    assert exc_info.value.status_code == 401
    # Only 1 attempt, no retries.
    assert len(fake_client.embeddings.calls) == 1
    mock_sleep.assert_not_called()


# ── 4.5 响应长度不匹配 / 维度不匹配 ───────────────────────────────


# 返回 data 数组长度与输入不匹配时抛出 EmbeddingInvalidResponseError。
def test_embed_raises_invalid_response_on_length_mismatch():
    module = get_adapter_module()
    config = make_config(dimensions=3)

    # Request 3 texts but response has only 2 items.
    response = make_fake_response(
        [
            make_fake_embedding_item(0, [0.1, 0.2, 0.3]),
            make_fake_embedding_item(1, [0.4, 0.5, 0.6]),
        ]
    )
    fake_client = FakeClient(responses=[response])
    adapter = module.EmbeddingAdapter(config=config, client=fake_client)

    with pytest.raises(module.EmbeddingInvalidResponseError, match="Expected 3"):
        adapter.embed(["a", "b", "c"])


# 返回向量维度与配置不一致时抛出 EmbeddingInvalidResponseError。
def test_embed_raises_invalid_response_on_dimension_mismatch():
    module = get_adapter_module()
    config = make_config(dimensions=128)

    # Response returns 3-dim vector but config expects 128.
    response = make_fake_response([make_fake_embedding_item(0, [0.1, 0.2, 0.3])])
    fake_client = FakeClient(responses=[response])
    adapter = module.EmbeddingAdapter(config=config, client=fake_client)

    with pytest.raises(module.EmbeddingInvalidResponseError, match="Expected 128"):
        adapter.embed_single("test")


# ── 4.6 EmbeddingConfig.from_settings() ───────────────────────────


# from_settings() 应将 Settings 对象上的 DOCUMENT_EMBEDDING_* 字段正确映射到 dataclass。
def test_embedding_config_from_settings_maps_all_fields():
    config_module = get_config_module()

    class FakeSettings:
        document_embedding_api_base_url = "https://api.example.com/v1"
        document_embedding_api_key = "sk-fake"
        document_embedding_model = "Qwen/Qwen3-Embedding-0.6B"
        document_embedding_dimensions = 1024
        document_embedding_encoding_format = "float"
        document_embedding_batch_size = 100
        document_embedding_max_retries = 3
        document_embedding_request_timeout = 60.0

    config = config_module.EmbeddingConfig.from_settings(FakeSettings())

    assert config.api_base_url == "https://api.example.com/v1"
    assert config.api_key == "sk-fake"
    assert config.model == "Qwen/Qwen3-Embedding-0.6B"
    assert config.dimensions == 1024
    assert config.encoding_format == "float"
    assert config.batch_size == 100
    assert config.max_retries == 3
    assert config.request_timeout == 60.0


# from_settings() 不传参时应使用全局 Settings（通过 get_settings()）。
def test_embedding_config_from_settings_uses_global_settings_by_default():
    config_module = get_config_module()
    from app.core.config import Settings

    config = config_module.EmbeddingConfig.from_settings()

    settings = Settings(_env_file=None)
    assert config.dimensions == settings.document_embedding_dimensions
    assert config.batch_size == settings.document_embedding_batch_size
    assert config.max_retries == settings.document_embedding_max_retries
    assert config.request_timeout == settings.document_embedding_request_timeout


# snapshot() 应返回包含关键配置项的字典，不含敏感信息。
def test_embedding_config_snapshot_excludes_sensitive_fields():
    config = make_config(api_key="sk-secret")

    snap = config.snapshot()

    assert "api_key" not in snap
    assert snap["api_base_url"] == "https://test-api.example.com/v1"
    assert snap["model"] == "test-model"
    assert snap["dimensions"] == 128
    assert snap["encoding_format"] == "float"
    assert snap["batch_size"] == 10


# ── 其他边界测试 ──────────────────────────────────────────────────


# embed() 应将 config 参数正确传递给 API 调用。
def test_embed_passes_config_parameters_to_api():
    module = get_adapter_module()
    config = make_config(
        model="custom-model",
        dimensions=768,
        encoding_format="base64",
    )
    fake_client = FakeClient(
        responses=[make_fake_response([make_fake_embedding_item(0, [0.0] * 768)])]
    )
    adapter = module.EmbeddingAdapter(config=config, client=fake_client)

    adapter.embed(["test"])

    call = fake_client.embeddings.calls[0]
    assert call["model"] == "custom-model"
    assert call["dimensions"] == 768
    assert call["encoding_format"] == "base64"
    assert call["input"] == ["test"]


# 维度校验错误不应触发重试（响应格式错误不是网络问题）。
def test_embed_does_not_retry_on_invalid_response():
    module = get_adapter_module()
    config = make_config(max_retries=3, dimensions=10)

    # Response has wrong dimension — should fail immediately, no retry.
    response = make_fake_response(
        [make_fake_embedding_item(0, [1.0, 2.0])]  # 2 dims, config expects 10
    )
    fake_client = FakeClient(responses=[response])
    adapter = module.EmbeddingAdapter(config=config, client=fake_client)

    with (
        patch("time.sleep", return_value=None) as mock_sleep,
        pytest.raises(module.EmbeddingInvalidResponseError),
    ):
        adapter.embed_single("test")

    mock_sleep.assert_not_called()
    # Only 1 attempt — validation errors are not network errors.
    assert len(fake_client.embeddings.calls) == 1


# ── 4.7 token_count 提取与分配 ─────────────────────────────────────


# 当 API 响应包含 usage.total_tokens 时，应将其按公平整分配至每个 EmbeddingResult。
def test_validate_response_distributes_token_count_evenly():
    module = get_adapter_module()
    config = make_config(dimensions=3, batch_size=10)

    # usage.total_tokens = 100, expected_count = 3
    # base = 33, remainder = 1 → [34, 33, 33]
    usage = SimpleNamespace(total_tokens=100)
    items = [
        make_fake_embedding_item(0, [1.0, 2.0, 3.0]),
        make_fake_embedding_item(1, [4.0, 5.0, 6.0]),
        make_fake_embedding_item(2, [7.0, 8.0, 9.0]),
    ]
    response = SimpleNamespace(data=items, usage=usage)
    fake_client = FakeClient(responses=[response])
    adapter = module.EmbeddingAdapter(config=config, client=fake_client)

    results = adapter.embed(["a", "b", "c"])

    assert len(results) == 3
    # First item gets the remainder
    assert results[0].token_count == 34
    assert results[1].token_count == 33
    assert results[2].token_count == 33


# 当 API 响应不含 usage 对象时，token_count 应为 None。
def test_validate_response_without_usage_returns_none_token_count():
    module = get_adapter_module()
    config = make_config(dimensions=2)

    response = make_fake_response(
        [make_fake_embedding_item(0, [1.0, 2.0])]
    )
    # Ensure response has no usage attribute
    assert not hasattr(response, "usage")

    fake_client = FakeClient(responses=[response])
    adapter = module.EmbeddingAdapter(config=config, client=fake_client)

    result = adapter.embed_single("hello")

    assert result.token_count is None


# batch 拆分时 token_count 应在子批次结果重索引时保留。
def test_token_count_preserved_across_batch_splits():
    module = get_adapter_module()
    config = make_config(batch_size=2, dimensions=1)

    # Batch 1: total_tokens=20 for 2 items → 10 each
    usage1 = SimpleNamespace(total_tokens=20)
    batch1 = SimpleNamespace(
        data=[
            make_fake_embedding_item(0, [1.0]),
            make_fake_embedding_item(1, [2.0]),
        ],
        usage=usage1,
    )
    # Batch 2: total_tokens=15 for 2 items → 8 and 7
    usage2 = SimpleNamespace(total_tokens=15)
    batch2 = SimpleNamespace(
        data=[
            make_fake_embedding_item(0, [3.0]),
            make_fake_embedding_item(1, [4.0]),
        ],
        usage=usage2,
    )

    fake_client = FakeClient(responses=[batch1, batch2])
    adapter = module.EmbeddingAdapter(config=config, client=fake_client)

    results = adapter.embed(["a", "b", "c", "d"])

    assert len(results) == 4
    assert results[0].token_count == 10
    assert results[1].token_count == 10
    assert results[2].token_count == 8  # remainder to first in batch
    assert results[3].token_count == 7
