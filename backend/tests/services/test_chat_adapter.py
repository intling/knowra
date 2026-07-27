# 本文件验证 ChatAdapter 对 OpenAI 兼容 chat completion API 的封装。
# 覆盖正常生成、超时重试、5xx 重试、4xx 不重试、重试耗尽抛错和配置工厂方法。

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# ── helpers ──────────────────────────────────────────────────────────


def get_adapter_module():
    return import_module("app.services.chat_adapter")


def get_config_module():
    return import_module("app.services.chat_config")


def make_config(**overrides):
    """Build a ChatConfig with sensible test defaults."""
    config_module = get_config_module()
    defaults = {
        "api_base_url": "https://test-api.example.com/v1",
        "api_key": "sk-test-key",
        "model": "test-chat-model",
        "temperature": 0.1,
        "max_tokens": 1024,
        "request_timeout": 30.0,
        "max_retries": 3,
    }
    defaults.update(overrides)
    return config_module.ChatConfig(**defaults)


def make_fake_chat_completion(content: str = "Hello, world!"):
    """Create a fake OpenAI chat.completions.create() response."""
    message = SimpleNamespace(
        role="assistant",
        content=content,
    )
    choice = SimpleNamespace(
        index=0,
        message=message,
        finish_reason="stop",
    )
    usage = SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
    )
    return SimpleNamespace(
        id="chatcmpl-fake",
        object="chat.completion",
        created=1234567890,
        model="test-chat-model",
        choices=[choice],
        usage=usage,
    )


def make_mock_response(status_code: int = 200):
    """Create a mock httpx.Response-like object for APIStatusError."""
    from unittest.mock import MagicMock

    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    return mock_resp


class FakeChatCompletions:
    """A fake ``client.chat.completions`` that records calls and returns canned responses."""

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
        return make_fake_chat_completion()


class FakeClient:
    """A fake OpenAI client whose ``chat`` attribute provides ``completions``."""

    def __init__(self, responses=None, side_effect=None):
        self.chat = SimpleNamespace(
            completions=FakeChatCompletions(responses=responses, side_effect=side_effect)
        )


# ── 1. 正常生成 ──────────────────────────────────────────────────────


# 正常生成应返回 ChatResult，包含 content 和 token 统计。
def test_generate_returns_chat_result_with_content_and_tokens():
    module = get_adapter_module()
    config = make_config()
    fake_client = FakeClient(responses=[make_fake_chat_completion(content="The answer is 42.")])
    adapter = module.ChatAdapter(config=config, client=fake_client)

    result = adapter.generate(messages=[{"role": "user", "content": "What is the answer?"}])

    assert isinstance(result, module.ChatResult)
    assert result.content == "The answer is 42."
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    assert result.total_tokens == 15
    assert result.model == "test-chat-model"


# ── 2. 超时重试 ──────────────────────────────────────────────────────


# 网络超时时适配器应自动重试，超过 max_retries 后抛出 ChatAPIError。
def test_generate_retries_on_timeout_then_raises_chat_api_error():
    module = get_adapter_module()
    config = make_config(max_retries=2)

    from openai import APITimeoutError

    timeout_error = APITimeoutError("Request timed out")
    fake_client = FakeClient(side_effect=timeout_error)
    adapter = module.ChatAdapter(config=config, client=fake_client)

    with (
        patch("time.sleep", return_value=None) as mock_sleep,
        pytest.raises(module.ChatAPIError, match="timed out"),
    ):
        adapter.generate(messages=[{"role": "user", "content": "test"}])

    # max_retries=2 → 3 total attempts, 2 sleeps between them
    assert mock_sleep.call_count == 2
    assert fake_client.chat.completions.calls


# ── 3. 5xx 重试 ──────────────────────────────────────────────────────


# API 返回 5xx 时适配器应自动重试，重试耗尽后抛出 ChatAPIError 并携带状态码。
def test_generate_retries_on_5xx():
    module = get_adapter_module()
    config = make_config(max_retries=2)

    from openai import APIStatusError

    server_error = APIStatusError(
        "Internal Server Error",
        response=make_mock_response(status_code=500),
        body=None,
    )
    fake_client = FakeClient(side_effect=server_error)
    adapter = module.ChatAdapter(config=config, client=fake_client)

    with (
        patch("time.sleep", return_value=None),
        pytest.raises(module.ChatAPIError) as exc_info,
    ):
        adapter.generate(messages=[{"role": "user", "content": "test"}])

    assert exc_info.value.status_code == 500
    # 3 total attempts (initial + 2 retries).
    assert len(fake_client.chat.completions.calls) == 3


# ── 4. 4xx（除 429 外）不重试 ──────────────────────────────────────────


# API 返回 4xx（如 401 认证失败、403 权限不足）时适配器应立即失败不重试。
# 429 Rate Limit 是唯一例外——属于临时性错误，应重试（见第 5 节）。
def test_generate_fails_immediately_on_4xx():
    module = get_adapter_module()
    config = make_config(max_retries=3)

    from openai import APIStatusError

    auth_error = APIStatusError(
        "Unauthorized",
        response=make_mock_response(status_code=401),
        body=None,
    )
    fake_client = FakeClient(side_effect=auth_error)
    adapter = module.ChatAdapter(config=config, client=fake_client)

    with (
        patch("time.sleep", return_value=None) as mock_sleep,
        pytest.raises(module.ChatAPIError) as exc_info,
    ):
        adapter.generate(messages=[{"role": "user", "content": "test"}])

    assert exc_info.value.status_code == 401
    # Only 1 attempt, no retries.
    assert len(fake_client.chat.completions.calls) == 1
    mock_sleep.assert_not_called()


# ── 5. 429 Rate Limit 重试 ────────────────────────────────────────────


# 429 Too Many Requests 是 LLM API 最常见临时性错误，应自动重试。
# 重试耗尽后抛出 ChatAPIError 并携带 429 状态码。
def test_generate_retries_on_429_rate_limit():
    module = get_adapter_module()
    config = make_config(max_retries=2)

    from openai import APIStatusError

    rate_limit_error = APIStatusError(
        "Too Many Requests",
        response=make_mock_response(status_code=429),
        body=None,
    )
    fake_client = FakeClient(side_effect=rate_limit_error)
    adapter = module.ChatAdapter(config=config, client=fake_client)

    with (
        patch("time.sleep", return_value=None),
        pytest.raises(module.ChatAPIError) as exc_info,
    ):
        adapter.generate(messages=[{"role": "user", "content": "test"}])

    assert exc_info.value.status_code == 429
    # 3 total attempts (initial + 2 retries).
    assert len(fake_client.chat.completions.calls) == 3


# 首次 429、重试成功后应返回完整 ChatResult。
def test_generate_recovers_after_429_retry():
    module = get_adapter_module()
    config = make_config(max_retries=2)

    from openai import APIStatusError

    rate_limit_error = APIStatusError(
        "Too Many Requests",
        response=make_mock_response(status_code=429),
        body=None,
    )
    success_response = make_fake_chat_completion(content="Rate limit recovered!")
    fake_client = FakeClient(side_effect=[rate_limit_error, success_response])
    adapter = module.ChatAdapter(config=config, client=fake_client)

    with patch("time.sleep", return_value=None):
        result = adapter.generate(messages=[{"role": "user", "content": "test"}])

    assert result.content == "Rate limit recovered!"
    assert len(fake_client.chat.completions.calls) == 2


# 429 带 Retry-After 头时应按服务端建议时长等待后重试。
def test_generate_respects_retry_after_header_for_429():
    module = get_adapter_module()
    config = make_config(max_retries=1)

    from openai import APIStatusError

    mock_response = make_mock_response(status_code=429)
    mock_response.headers = {"Retry-After": "3.5"}
    rate_limit_error = APIStatusError(
        "Too Many Requests",
        response=mock_response,
        body=None,
    )
    success_response = make_fake_chat_completion(content="After Retry-After wait!")
    fake_client = FakeClient(side_effect=[rate_limit_error, success_response])
    adapter = module.ChatAdapter(config=config, client=fake_client)

    with patch("time.sleep", return_value=None) as mock_sleep:
        result = adapter.generate(messages=[{"role": "user", "content": "test"}])

    assert result.content == "After Retry-After wait!"
    # Should have slept exactly once, using the Retry-After value.
    mock_sleep.assert_called_once_with(3.5)


# ── 6. 重试耗尽抛错 ──────────────────────────────────────────────────


# 首次成功、首次失败后重试成功也应验证重试恢复路径。
def test_generate_recovers_on_retry():
    module = get_adapter_module()
    config = make_config(max_retries=2)

    from openai import APITimeoutError

    timeout_error = APITimeoutError("Request timed out")
    success_response = make_fake_chat_completion(content="Recovered!")
    fake_client = FakeClient(side_effect=[timeout_error, success_response])
    adapter = module.ChatAdapter(config=config, client=fake_client)

    with patch("time.sleep", return_value=None):
        result = adapter.generate(messages=[{"role": "user", "content": "test"}])

    assert result.content == "Recovered!"
    assert len(fake_client.chat.completions.calls) == 2


# 连接错误应触发重试。
def test_generate_retries_on_connection_error():
    module = get_adapter_module()
    config = make_config(max_retries=2)

    from unittest.mock import MagicMock

    from openai import APIConnectionError

    mock_request = MagicMock()
    conn_error = APIConnectionError(message="Connection refused", request=mock_request)
    fake_client = FakeClient(side_effect=conn_error)
    adapter = module.ChatAdapter(config=config, client=fake_client)

    with (
        patch("time.sleep", return_value=None) as mock_sleep,
        pytest.raises(module.ChatAPIError, match="Connection refused"),
    ):
        adapter.generate(messages=[{"role": "user", "content": "test"}])

    # Should have retried.
    assert mock_sleep.call_count == 2
    assert len(fake_client.chat.completions.calls) == 3


# ── 7. ChatConfig.from_settings() ─────────────────────────────────────


# from_settings() 应将 Settings 对象上的 chat_* 字段正确映射到 dataclass。
def test_chat_config_from_settings_maps_all_fields():
    config_module = get_config_module()

    class FakeSettings:
        chat_api_base_url = "https://api.example.com/v1"
        chat_api_key = "sk-fake"
        chat_model = "qwen/qwen3.5-plus"
        chat_temperature = 0.3
        chat_max_tokens = 2048
        chat_request_timeout = 45.0
        chat_max_retries = 5

    config = config_module.ChatConfig.from_settings(FakeSettings())

    assert config.api_base_url == "https://api.example.com/v1"
    assert config.api_key == "sk-fake"
    assert config.model == "qwen/qwen3.5-plus"
    assert config.temperature == 0.3
    assert config.max_tokens == 2048
    assert config.request_timeout == 45.0
    assert config.max_retries == 5


# from_settings() 不传参时应使用全局 Settings（通过 get_settings()）。
def test_chat_config_from_settings_uses_global_settings_by_default():
    config_module = get_config_module()
    from app.core.config import Settings

    config = config_module.ChatConfig.from_settings()

    settings = Settings(_env_file=None)
    assert config.model == settings.chat_model
    assert config.temperature == settings.chat_temperature
    assert config.max_tokens == settings.chat_max_tokens
    assert config.max_retries == settings.chat_max_retries
    assert config.request_timeout == settings.chat_request_timeout


# snapshot() 应返回包含关键配置项的字典，不含敏感信息。
def test_chat_config_snapshot_excludes_sensitive_fields():
    config = make_config(api_key="sk-secret")

    snap = config.snapshot()

    assert "api_key" not in snap
    assert snap["api_base_url"] == "https://test-api.example.com/v1"
    assert snap["model"] == "test-chat-model"
    assert snap["temperature"] == 0.1
    assert snap["max_tokens"] == 1024
    assert snap["request_timeout"] == 30.0
    assert snap["max_retries"] == 3


# ── 8. 参数传递验证 ──────────────────────────────────────────────────


# generate() 应将 config 参数正确传递给 API 调用。
def test_generate_passes_config_parameters_to_api():
    module = get_adapter_module()
    config = make_config(
        model="custom-model",
        temperature=0.2,
        max_tokens=512,
    )
    fake_client = FakeClient(responses=[make_fake_chat_completion()])
    adapter = module.ChatAdapter(config=config, client=fake_client)

    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello"},
    ]
    adapter.generate(messages=messages)

    call = fake_client.chat.completions.calls[0]
    assert call["model"] == "custom-model"
    assert call["temperature"] == 0.2
    assert call["max_tokens"] == 512
    assert call["messages"] == messages


# ── 9. stream 参数预留 ────────────────────────────────────────────────


# stream=False（默认）时正常返回 ChatResult。
def test_generate_with_stream_false_returns_chat_result():
    module = get_adapter_module()
    config = make_config()
    fake_client = FakeClient(responses=[make_fake_chat_completion(content="Normal response.")])
    adapter = module.ChatAdapter(config=config, client=fake_client)

    result = adapter.generate(
        messages=[{"role": "user", "content": "test"}],
        stream=False,
    )

    assert isinstance(result, module.ChatResult)
    assert result.content == "Normal response."


# stream=True 时抛出 NotImplementedError。
def test_generate_with_stream_true_raises_not_implemented_error():
    module = get_adapter_module()
    config = make_config()
    fake_client = FakeClient()
    adapter = module.ChatAdapter(config=config, client=fake_client)

    with pytest.raises(NotImplementedError, match="Streaming will be implemented in Phase 2"):
        adapter.generate(
            messages=[{"role": "user", "content": "test"}],
            stream=True,
        )


# ── 10. 超时重试恢复后继续 ────────────────────────────────────────────


# 5xx 重试成功后也应返回正确的结果。
def test_generate_recovers_after_5xx_retry():
    module = get_adapter_module()
    config = make_config(max_retries=2)

    from openai import APIStatusError

    server_error = APIStatusError(
        "Service Unavailable",
        response=make_mock_response(status_code=503),
        body=None,
    )
    success_response = make_fake_chat_completion(content="Recovered from 5xx!")
    fake_client = FakeClient(side_effect=[server_error, success_response])
    adapter = module.ChatAdapter(config=config, client=fake_client)

    with patch("time.sleep", return_value=None):
        result = adapter.generate(messages=[{"role": "user", "content": "test"}])

    assert result.content == "Recovered from 5xx!"
    assert len(fake_client.chat.completions.calls) == 2


# ── 11. 日志验证 ─────────────────────────────────────────────────────


# ChatAdapter 应使用结构化日志记录生成请求。
def test_generate_logs_request_info():
    module = get_adapter_module()
    config = make_config()
    fake_client = FakeClient(responses=[make_fake_chat_completion()])
    adapter = module.ChatAdapter(config=config, client=fake_client)

    with patch.object(adapter, "_logger") as mock_logger:
        adapter.generate(
            messages=[{"role": "user", "content": "Hello"}],
        )

        # Verify at least one log call was made with request info.
        assert mock_logger.info.called


# ── 12. API 响应无 usage 时的容错 ─────────────────────────────────────


# 当 API 响应不含 usage 对象时，token 统计字段应为 0。
def test_generate_handles_missing_usage_gracefully():
    module = get_adapter_module()
    config = make_config()

    # Create response without usage
    message = SimpleNamespace(role="assistant", content="No usage data")
    choice = SimpleNamespace(index=0, message=message, finish_reason="stop")
    response_no_usage = SimpleNamespace(
        id="chatcmpl-no-usage",
        object="chat.completion",
        created=1234567890,
        model="test-chat-model",
        choices=[choice],
    )
    fake_client = FakeClient(responses=[response_no_usage])
    adapter = module.ChatAdapter(config=config, client=fake_client)

    result = adapter.generate(messages=[{"role": "user", "content": "test"}])

    assert result.content == "No usage data"
    assert result.prompt_tokens == 0
    assert result.completion_tokens == 0
    assert result.total_tokens == 0
