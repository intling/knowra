"""模型结束状态回归：使用真实 SDK 解析 SSE，网络仅由 MockTransport 替换。"""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from openai import AsyncOpenAI

from app.core.config import Settings
from app.services.chat_adapter import ChatAdapter
from app.services.chat_config import ChatConfig
from tests.search_helpers import make_fake_chat_config


@pytest.mark.parametrize("reason", ["stop", "length", "content_filter"])
def test_sync_completion_preserves_finish_reason(reason):
    """验证同步模型调用保留结束原因，避免丢失长度限制或过滤信息。"""
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content="已有正文"), finish_reason=reason)
        ],
        model="fixture",
        usage=None,
    )
    result = ChatAdapter._parse_response(response)
    assert getattr(result, "finish_reason", None) == reason


@pytest.mark.parametrize("reason", ["stop", "length", None])
def test_real_sse_parser_preserves_terminal_reason_and_usage(reason):
    """验证真实 SDK 流解析不丢失结束帧；无结束帧的正文必须标记中断。"""

    async def run():
        chunks = [
            {
                "choices": [
                    {"index": 0, "delta": {"content": "一、数据结构"}, "finish_reason": None}
                ]
            },
        ]
        if reason is not None:
            chunks.append({"choices": [{"index": 0, "delta": {}, "finish_reason": reason}]})
        chunks.append(
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 18434,
                    "completion_tokens": 1024,
                    "total_tokens": 19458,
                },
            }
        )
        sse = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n"
        transport = httpx.MockTransport(lambda _: httpx.Response(200, text=sse))
        adapter = ChatAdapter(config=make_fake_chat_config())
        adapter._async_client_cache = AsyncOpenAI(
            api_key="fixture",
            base_url="https://fixture.invalid/v1",
            http_client=httpx.AsyncClient(transport=transport),
        )
        try:
            return await adapter.generate_async([{"role": "user", "content": "解释概念"}])
        finally:
            await adapter.aclose()

    result = asyncio.run(run())
    assert result.content == "一、数据结构"
    assert result.total_tokens == 19458
    assert getattr(result, "finish_reason", None) == (reason or "stream_interrupted")


def test_stream_is_closed_when_collection_is_cancelled():
    """验证收集任务取消后关闭上游 SSE，避免续写超时遗留连接。"""

    class Stream:
        closed = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.sleep(10)

        async def close(self):
            self.closed = True

    async def run():
        stream = Stream()
        adapter = ChatAdapter(config=make_fake_chat_config())
        try:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(
                    adapter._collect_stream(stream, "fixture", first_token_timeout=10), 0.01
                )
            assert stream.closed, "取消生成后必须关闭上游流"
        finally:
            adapter.close()

    asyncio.run(run())


def test_chat_defaults_and_generation_deadline_are_configurable(monkeypatch):
    """验证长回答默认预算提升、总截止时间可配置且进入请求快照。"""
    monkeypatch.delenv("CHAT_MAX_TOKENS", raising=False)
    settings = Settings(_env_file=None)
    assert settings.chat_max_tokens == 4096
    monkeypatch.setenv("CHAT_GENERATION_TIMEOUT", "90")
    config = ChatConfig.from_settings(Settings(_env_file=None))
    assert getattr(config, "generation_timeout", None) == 90
    assert config.snapshot()["generation_timeout"] == 90
