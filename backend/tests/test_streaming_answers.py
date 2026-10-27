"""流式问答 RED：真实 SDK、回答编排、Cookie 与额度，只替换外部网络。"""

import asyncio
import json
from contextlib import suppress
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest
from openai import APIConnectionError, AsyncOpenAI
from sqlmodel import select

from app.api.deps import get_model_settings
from app.api.routes import search as routes
from app.core.config import get_settings
from app.main import app
from app.models.chat_quota import ChatUsage, UserChatLimit
from app.services.cache_manager import CacheManager
from app.services.chat_adapter import ChatAdapter, ChatAPIError
from app.services.search import SearchService
from tests.auth_helpers import login_as, make_account, seed_knowledge_chain
from tests.search_helpers import (
    make_fake_chat_config,
    make_fake_db_row,
    make_fake_embedding_adapter,
    make_fake_session,
)


def model_frame(*, content=None, reason=None, usage=False):
    payload = {
        "choices": []
        if usage
        else [{"index": 0, "delta": {"content": content}, "finish_reason": reason}]
    }
    if usage:
        payload["usage"] = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
    return ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode()


class ModelStream(httpx.AsyncByteStream):
    def __init__(
        self, *, parts=("第一段", "，第二段。"), reason="stop", fail=False, after_first=None
    ):
        self.parts = parts
        self.reason = reason
        self.fail = fail
        self.after_first = after_first
        self.closed = False

    async def __aiter__(self):
        for index, part in enumerate(self.parts):
            yield model_frame(content=part)
            if index == 0 and self.after_first is not None:
                await self.after_first()
        if self.fail:
            raise httpx.ReadError("受控的模型连接中断")
        yield model_frame(reason=self.reason)
        yield model_frame(usage=True)
        yield b"data: [DONE]\n\n"

    async def aclose(self):
        self.closed = True


def network_adapter(streams):
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        stream = streams[min(len(requests) - 1, len(streams) - 1)]
        return httpx.Response(200, stream=stream)

    adapter = ChatAdapter(config=make_fake_chat_config(max_retries=0))
    adapter._async_client_cache = AsyncOpenAI(
        api_key="fixture",
        base_url="https://fixture.invalid/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    return adapter, requests


def service_for(adapter, **kwargs):
    session = make_fake_session(rows=[make_fake_db_row()])
    session.exec.return_value.first.return_value = 1
    return SearchService(
        session=session,
        owner_user_id=uuid4(),
        embedding_adapter=make_fake_embedding_adapter(),
        chat_adapter=adapter,
        chat_config=make_fake_chat_config(),
        **kwargs,
    )


def parse_events(response):
    assert response.headers["content-type"].startswith("text/event-stream"), (
        "已请求 SSE，但仍收到整段 JSON；预期模型生成结束前交付正文增量"
    )
    events = []
    for frame in response.text.replace("\r\n", "\n").split("\n\n"):
        lines = frame.splitlines()
        event = next((line[6:].strip() for line in lines if line.startswith("event:")), None)
        data = "\n".join(line[5:].lstrip() for line in lines if line.startswith("data:"))
        if event and data:
            events.append((event, json.loads(data)))
    return events


def test_adapter_delivers_text_before_upstream_completion():
    """验证适配器在上游继续生成前通知正文增量，并保留最终用量和结束原因。"""

    async def run():
        received = []

        async def receive(delta):
            received.append(delta)

        async def check_first():
            assert received == ["第一段"], "首段仍被后端收集；应在模型结束前交付"

        stream = ModelStream(after_first=check_first)
        adapter, _ = network_adapter([stream])
        try:
            result = await adapter.generate_async([], on_delta=receive)
            assert received == ["第一段", "，第二段。"]
            assert result.content == "".join(received)
            assert result.finish_reason == "stop"
            assert result.total_tokens == 150
            assert stream.closed, "正常结束后应关闭模型响应流"
        finally:
            await adapter.aclose()

    asyncio.run(run())


def test_adapter_does_not_replay_already_delivered_text():
    """验证交付正文后发生可重试连接错误也不重放，避免用户收到重复内容。"""

    async def run():
        received = []

        async def receive(delta):
            received.append(delta)

        async def disconnect():
            raise APIConnectionError(request=httpx.Request("POST", "https://fixture.invalid/v1"))

        stream = ModelStream(parts=("第一段",), after_first=disconnect)
        adapter, requests = network_adapter([stream])
        adapter._compute_delay = lambda *_: 0
        try:
            with pytest.raises(ChatAPIError):
                await adapter.generate_async([], on_delta=receive, max_retries=2)
            assert len(requests) == 1, "已交付正文的同次生成不能自动重放"
            assert received == ["第一段"]
            assert stream.closed, "上游断流后必须释放连接"
        finally:
            await adapter.aclose()

    asyncio.run(run())


def test_cancel_from_consumer_closes_upstream_stream():
    """验证下游取消传播到模型读取任务，并关闭上游 SSE 连接。"""

    async def run():
        stream = ModelStream()
        adapter, _ = network_adapter([stream])

        async def cancel(_delta):
            raise asyncio.CancelledError

        try:
            with pytest.raises(asyncio.CancelledError):
                await adapter.generate_async([], on_delta=cancel)
            assert stream.closed, "消费者取消后模型响应流必须关闭"
        finally:
            await adapter.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("query,mode", [("你好", "general"), ("资料中的特征值是什么？", "rag")])
def test_service_sends_sources_before_text_and_streams_continuations(query, mode):
    """验证真实编排先交付来源元信息，再顺序流式续写并累计实际 token 用量。"""

    async def run():
        first = ModelStream(parts=("第一段",), reason="length")
        second = ModelStream(parts=("，续写完成。",))
        adapter, requests = network_adapter([first, second])
        service = service_for(adapter)
        events = []

        async def metadata(response):
            events.append(("metadata", response.model_dump()))

        async def delta(text):
            assert events and events[0][0] == "metadata", "正文前应已收到回答模式与来源"
            events.append(("delta", text))

        try:
            response = await service.search_async(query, on_metadata=metadata, on_delta=delta)
            assert events[0][1]["answer"] == ""
            assert events[0][1]["answer_tokens"] is None
            assert events[0][1]["answer_mode"] == mode
            assert bool(events[0][1]["results"]) == (mode == "rag")
            assert [data for kind, data in events if kind == "delta"] == ["第一段", "，续写完成。"]
            assert response.answer == "第一段，续写完成。"
            assert response.answer_tokens.total_tokens == 300
            assert response.answer_incomplete is False
            assert len(requests) == 2
            assert "第一段" in str(requests[1]["messages"])
        finally:
            await adapter.aclose()

    asyncio.run(run())


def test_service_keeps_current_partial_text_without_success_cache():
    """验证首次生成中途断开也保留当前正文及来源，标为未完成且不写成功缓存。"""

    async def run():
        adapter, _ = network_adapter([ModelStream(fail=True)])
        cache = MagicMock(wraps=CacheManager())
        breaker = MagicMock()
        service = service_for(adapter, response_cache=cache, circuit_breaker=breaker)
        received = []

        async def receive(text):
            received.append(text)

        try:
            response = await service.search_async(
                "资料中的特征值是什么？", session_id="stream-test", on_delta=receive
            )
            assert response.answer == "".join(received) == "第一段，第二段。"
            assert response.answer_incomplete is True
            assert response.results, "中断后的正文仍应能核对真实来源"
            assert response.generation_error is None
            assert response.answer_tokens is None, "上游没有给出用量时不能伪造零 token"
            cache.store.assert_not_called()
            breaker.on_failure.assert_called_once()
            breaker.on_success.assert_not_called()
        finally:
            await adapter.aclose()

    asyncio.run(run())


@pytest.fixture
def streaming_pipeline(auth_client, monkeypatch):
    streams = [ModelStream()]
    adapters = []
    requests = []

    async def provide_chat():
        adapter, calls = network_adapter(streams)
        adapters.append(adapter)
        requests.append(calls)
        try:
            yield adapter
        finally:
            await adapter.aclose()

    app.dependency_overrides.update(
        {
            get_model_settings: get_settings,
            routes.get_chat_config: lambda: make_fake_chat_config(),
            routes.get_embedding_adapter: lambda: make_fake_embedding_adapter(),
            routes.get_chat_adapter: provide_chat,
            routes.get_query_rewriter: lambda: None,
            routes.get_search_response_cache: lambda: None,
            routes.get_search_audit_trail: lambda: None,
            routes.get_chat_circuit_breaker: lambda: None,
            routes.get_rerank_adapter: lambda: None,
        }
    )
    monkeypatch.setattr(routes.SearchService, "_vector_search", lambda *_: [])
    return streams, requests


def test_sse_route_emits_metadata_deltas_and_final_response(
    auth_client, auth_db, streaming_pipeline
):
    """验证真实认证路由输出 SSE 元信息、正文增量和最终响应，同时禁止代理缓冲。"""
    user = make_account(auth_db)
    login_as(auth_client, auth_db, user)
    response = auth_client.post(
        "/api/search", json={"query": "你好"}, headers={"Accept": "text/event-stream"}
    )
    assert response.status_code == 200, response.text
    events = parse_events(response)
    assert events[0] == ("status", {"stage": "searching"})
    assert next(data for kind, data in events if kind == "metadata")["answer_mode"] == "general"
    assert "".join(data["delta"] for kind, data in events if kind == "delta") == "第一段，第二段。"
    assert events[-1][0] == "done"
    assert events[-1][1]["answer"] == "第一段，第二段。"
    assert events[-1][1]["answer_tokens"]["total_tokens"] == 150
    assert response.headers["x-accel-buffering"] == "no"
    assert "no-cache" in response.headers["cache-control"]


@pytest.mark.parametrize("fail,expected_usage", [(False, 1), (True, 0)])
def test_sse_quota_keeps_only_complete_success(
    auth_client, auth_db, streaming_pipeline, fail, expected_usage
):
    """验证完整流回答计额，非空中断正文释放预留并允许重试。"""
    user = make_account(auth_db)
    login_as(auth_client, auth_db, user)
    auth_db.add(UserChatLimit(user_id=user.id, hourly_limit=1))
    auth_db.commit()
    streaming_pipeline[0][:] = [ModelStream(fail=fail)]
    response = auth_client.post(
        "/api/search", json={"query": "你好"}, headers={"Accept": "text/event-stream"}
    )
    final = parse_events(response)[-1]
    assert final[0] == "done"
    assert final[1]["answer_incomplete"] is fail
    assert len(auth_db.exec(select(ChatUsage)).all()) == expected_usage
    retry = auth_client.post(
        "/api/search", json={"query": "你好"}, headers={"Accept": "text/event-stream"}
    )
    assert retry.status_code == (200 if fail else 429), retry.text
    if not fail:
        assert retry.json()["code"] == "chat_quota_exceeded"
        assert retry.json()["detail"] and int(retry.headers["Retry-After"]) > 0


def test_sse_summary_retains_selected_sources(auth_client, auth_db, streaming_pipeline, tmp_path):
    """验证流式总结仍按当前用户的显式范围输出真实来源及覆盖信息。"""
    user = make_account(auth_db)
    login_as(auth_client, auth_db, user)
    _, selected, *_ = seed_knowledge_chain(auth_db, tmp_path / "selected", user, vectors=1)
    _, unselected, *_ = seed_knowledge_chain(auth_db, tmp_path / "outside", user, vectors=1)
    response = auth_client.post(
        "/api/search",
        json={"query": "总结这些资料的核心观点", "document_ids": [str(selected.id)]},
        headers={"Accept": "text/event-stream"},
    )
    events = parse_events(response)
    for kind, data in events:
        if kind in ("metadata", "done"):
            assert data["answer_mode"] == "summary"
            assert {row["parsed_document_id"] for row in data["results"]} == {str(selected.id)}
            assert data["summary_coverage"]["document_count"] == 1
            assert str(unselected.id) not in str(data["results"])


@pytest.mark.parametrize(
    "case,expected_status", [("anonymous", 401), ("foreign", 404), ("invalid", 422)]
)
def test_sse_rejects_before_stream_start_with_safe_reason(
    auth_client, auth_db, streaming_pipeline, tmp_path, case, expected_status
):
    """回归守护：SSE 协商不得绕过认证、资料范围与字段校验，必须返回明确 HTTP 错误。"""
    body = {"query": "你好"}
    if case != "anonymous":
        user = make_account(auth_db)
        login_as(auth_client, auth_db, user)
    if case == "foreign":
        other = make_account(auth_db)
        _, document, *_ = seed_knowledge_chain(auth_db, tmp_path / "foreign", other, vectors=1)
        body["document_ids"] = [str(document.id)]
    elif case == "invalid":
        body["document_ids"] = ["not-a-uuid"]
    response = auth_client.post("/api/search", json=body, headers={"Accept": "text/event-stream"})
    assert response.status_code == expected_status, response.text
    assert response.json()["detail"], "流开始前拒绝必须说明具体原因"
    assert not any(streaming_pipeline[1]), "校验失败不得请求模型"


@pytest.mark.parametrize("with_middleware", [True, False])
def test_disconnect_releases_reservation_and_closes_model_stream(
    auth_client, auth_db, streaming_pipeline, with_middleware
):
    """验证首段在模型结束前送达、在途额度仍保留，断开客户端后释放额度并关闭模型。"""
    from fastapi import FastAPI
    from starlette.requests import ClientDisconnect

    user = make_account(auth_db)
    login_as(auth_client, auth_db, user)
    auth_db.add(UserChatLimit(user_id=user.id, hourly_limit=1))
    auth_db.commit()
    asgi_app = app
    if not with_middleware:
        asgi_app = FastAPI()
        asgi_app.include_router(routes.router, prefix="/api")
        asgi_app.dependency_overrides.update(app.dependency_overrides)

    async def run():
        async def pause_after_first():
            await asyncio.sleep(0.3)

        stream = ModelStream(after_first=pause_after_first)
        streaming_pipeline[0][:] = [stream]
        request = auth_client.build_request(
            "POST", "/api/search", json={"query": "你好"}, headers={"Accept": "text/event-stream"}
        )
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/search",
            "raw_path": b"/api/search",
            "query_string": b"",
            "root_path": "",
            "headers": [(name.lower(), value) for name, value in request.headers.raw],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
        requested = False
        delivered = False
        output = b""

        async def receive():
            nonlocal requested
            if not requested:
                requested = True
                return {"type": "http.request", "body": request.content, "more_body": False}
            await asyncio.Event().wait()

        async def send(message):
            nonlocal delivered, output
            if message["type"] == "http.response.start":
                assert message["status"] == 200, "流式取消测试须先通过真实认证及额度准入"
            if message["type"] == "http.response.body":
                output += message.get("body", b"")
                if b"event: delta" in output:
                    delivered = True
                    assert not stream.closed, "首段必须在模型流结束前交付，不能完整收集后伪装流式"
                    assert len(auth_db.exec(select(ChatUsage)).all()) == 1, (
                        "流尚未结束时必须保留在途预留，避免并发请求绕过额度"
                    )
                    raise OSError("测试客户端已经断开")

        with suppress(ClientDisconnect, OSError):
            await asyncio.wait_for(asgi_app(scope, receive, send), timeout=3)
        assert delivered, "请求结束仍未收到正文 delta，预期在生成期间流式交付"
        assert stream.closed, "客户端断开后必须关闭供应商响应流"
        assert auth_db.exec(select(ChatUsage)).all() == [], "取消的回答不能占用成功额度"

    asyncio.run(run())


def test_json_search_remains_compatible(auth_client, auth_db, streaming_pipeline):
    """回归守护：未协商 SSE 的调用继续返回完整 SearchResponse JSON。"""
    user = make_account(auth_db)
    login_as(auth_client, auth_db, user)
    response = auth_client.post("/api/search", json={"query": "你好"})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["answer"] == "第一段，第二段。"
    assert response.json()["answer_tokens"]["total_tokens"] == 150
