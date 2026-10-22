"""后台配置必须进入真实依赖和自动任务，不只保存在配置页。"""

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Annotated
from unittest.mock import AsyncMock, MagicMock

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.routes import search
from app.core.config import get_settings
from app.db.session import get_session
from tests.admin_console.helpers import activate_profile, create_profile


# 验证搜索的真实依赖构造使用数据库中已选模型，而不是仍使用 get_settings 的环境值。
def test_search_dependency_reads_active_profile(auth_client, auth_db, admin_actor, model_settings):
    profile = create_profile(auth_client, model="database-chat")
    activate_profile(auth_client, profile)
    probe = FastAPI()
    probe.dependency_overrides[get_session] = lambda: auth_db
    probe.dependency_overrides[get_settings] = lambda: model_settings

    @probe.get("/probe")
    def config(value: Annotated[object, Depends(search.get_chat_config)]):
        return value.snapshot()

    with TestClient(probe) as client:
        response = client.get("/probe")
    assert response.status_code == 200, response.text
    assert response.json()["model"] == "database-chat", "搜索依赖仍在读取环境配置"


# 验证配置版本变化后不复用旧模型的搜索缓存、改写器和熔断器。
def test_model_revision_isolates_runtime_state(monkeypatch, model_settings):
    for name in (
        "_search_response_cache_singleton",
        "_chat_circuit_breaker_singleton",
        "_query_rewriter_singleton",
    ):
        monkeypatch.setattr(search, name, None)
    monkeypatch.setattr(search, "_search_response_cache_disabled", False)
    monkeypatch.setattr(search, "_query_rewriter_singleton_disabled", False)
    first = model_settings.model_copy(update={"model_configuration_revision": "chat:1"})
    second = model_settings.model_copy(update={"model_configuration_revision": "chat:2"})
    cache = search.get_search_response_cache(first)
    breaker = search.get_chat_circuit_breaker(first)
    search.get_query_rewriter(first, None)
    assert search.get_search_response_cache(second) is not cache, "新模型不得复用旧搜索响应缓存"
    assert search.get_chat_circuit_breaker(second) is not breaker, "新模型不得继承旧熔断状态"


# 验证自动向量化工厂使用后台默认的模型和密钥，不回退环境配置。
def test_automatic_embedding_uses_profile(auth_client, auth_db, admin_actor, model_settings):
    from app.services.document_parse_dispatcher import make_document_embedding_service

    profile = create_profile(auth_client, "embedding", model="active-embedding")
    activate_profile(auth_client, profile)
    service = make_document_embedding_service(session=auth_db, settings=model_settings)
    assert service.config.model == "active-embedding", "自动向量化没有接入后台默认配置"


# 验证重新向量化后台执行器接受入队快照，后台启动前配置变化也不覆盖快照。
def test_reembed_worker_accepts_inflight_configuration(auth_db, model_settings, monkeypatch):
    from app.api.routes import document_embedding as route
    from app.services.embedding_config import EmbeddingConfig

    config = EmbeddingConfig.from_settings(model_settings)
    job = SimpleNamespace(id="job", chunk_job_id="chunks", status="queued")
    fake_session = MagicMock()
    fake_session.get.return_value = job
    fake_session.exec.return_value.all.return_value = [SimpleNamespace(text="片段")]
    monkeypatch.setattr(route, "_coerce_uuid", lambda value: value)
    factory = MagicMock()
    monkeypatch.setattr(route, "DocumentEmbeddingService", factory)

    @contextmanager
    def session_factory():
        yield fake_session

    route.run_reembed_job(
        "job", session_factory=session_factory, embedding_adapter=object(), config=config
    )
    assert factory.call_args.kwargs["config"] is config


# 验证无鉴权本地聊天服务可使用空密钥，环境未配置时的既有校验仍保留。
def test_local_chat_profile_accepts_no_api_key(auth_client, auth_db, admin_actor, model_settings):
    from app.services.chat_adapter import ChatAdapter
    from app.services.chat_config import ChatConfig
    from app.services.model_configuration import resolve_model_settings

    profile = create_profile(auth_client, api_key="", base_url="http://localhost:11434/v1")
    activate_profile(auth_client, profile)
    effective = resolve_model_settings(auth_db, model_settings)
    adapter = ChatAdapter(config=ChatConfig.from_settings(effective))
    adapter._client.close()


# 验证请求级客户端在响应结束后释放，不因每次保存和切换配置积累连接。
def test_request_adapter_is_closed_after_response(
    auth_client, auth_db, admin_actor, model_settings, monkeypatch
):
    adapter = MagicMock()
    adapter.aclose = AsyncMock(side_effect=lambda: adapter.close())
    monkeypatch.setattr(search, "ChatAdapter", lambda **kwargs: adapter)
    probe = FastAPI()
    probe.dependency_overrides[get_session] = lambda: auth_db
    probe.dependency_overrides[get_settings] = lambda: model_settings

    @probe.get("/probe")
    def endpoint(value: Annotated[object, Depends(search.get_chat_adapter)]):
        return {"ok": True}

    with TestClient(probe) as client:
        assert client.get("/probe").status_code == 200
    adapter.close.assert_called_once()


# 验证共享改写器只共享缓存，每次 LLM 调用结束都关闭连接，失败也能释放。
def test_rewrite_adapter_releases_each_call(model_settings, monkeypatch):
    from app.services import chat_adapter as module
    from app.services.query_rewrite_config import QueryRewriteConfig

    client = MagicMock()
    client.generate.side_effect = RuntimeError("test failure")
    monkeypatch.setattr(module, "ChatAdapter", lambda **kwargs: client)
    adapter = module.TransientChatAdapter(config=QueryRewriteConfig.from_settings(model_settings))
    import pytest

    with pytest.raises(RuntimeError, match="test failure"):
        adapter.generate([{"role": "user", "content": "问题"}], request_timeout=1)
    client.close.assert_called_once()


# 验证后台默认 Embedding 可启用自动向量化，即使环境开关原先关闭。
def test_auto_embedding_activates_when_environment_disabled(
    auth_client, auth_db, admin_actor, model_settings, monkeypatch, tmp_path
):
    from app.models.document_parsing import DocumentParseJob
    from app.services import document_parse_dispatcher as module
    from tests.document_parsing_helpers import SessionFactory, make_uploaded_file
    from tests.services.test_document_parse_dispatcher import FakeParser

    profile = create_profile(auth_client, "embedding")
    activate_profile(auth_client, profile)
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: model_settings.model_copy(update={"document_embedding_enabled": False}),
    )
    upload = make_uploaded_file(auth_db, tmp_path / "uploads", admin_actor)
    job = DocumentParseJob(uploaded_file_id=upload.id, owner_user_id=admin_actor.id)
    auth_db.add(job)
    auth_db.commit()
    embedding = MagicMock()
    module.run_parse_job(
        job.id,
        session_factory=SessionFactory(auth_db),
        parser=FakeParser(),
        upload_storage_root=tmp_path / "uploads",
        artifact_storage_root=tmp_path / "parsed",
        document_chunking_enabled=True,
        chunking_service=MagicMock(),
        embedding_service=embedding,
    )
    embedding.run_initial_embedding.assert_called_once()


# 验证普通成员不能在请求体覆盖管理员已选的向量空间。
def test_reembed_cannot_override_managed_embedding(model_settings):
    import pytest

    from app.api.routes.document_embedding import _make_embedding_config
    from app.core.errors import AppError
    from app.schemas.document_embedding import ReEmbedRequest

    effective = model_settings.model_copy(update={"configured_model_kinds": ("embedding",)})
    with pytest.raises(AppError) as caught:
        _make_embedding_config(settings=effective, request=ReEmbedRequest(model="different-space"))
    assert caught.value.code == "embedding_configuration_managed"


# 验证本地 Embedding 服务无密钥时仍可构建客户端。
def test_local_embedding_without_key(model_settings):
    from app.services.embedding_adapter import EmbeddingAdapter
    from app.services.embedding_config import EmbeddingConfig

    effective = model_settings.model_copy(update={"document_embedding_api_key": ""})
    adapter = EmbeddingAdapter(config=EmbeddingConfig.from_settings(effective))
    adapter.close()


# 验证 worker 自己构造的客户端在成功或失败后释放。
def test_reembed_worker_closes_owned_adapter(model_settings, monkeypatch):
    from app.api.routes import document_embedding as route
    from app.services.embedding_config import EmbeddingConfig

    config = EmbeddingConfig.from_settings(model_settings)
    job = SimpleNamespace(id="job", chunk_job_id="chunks", status="queued")
    fake_session = MagicMock()
    fake_session.get.return_value = job
    fake_session.exec.return_value.all.return_value = [SimpleNamespace(text="片段")]
    adapter = MagicMock()
    monkeypatch.setattr(route, "_coerce_uuid", lambda value: value)
    monkeypatch.setattr(route, "EmbeddingAdapter", lambda **kwargs: adapter)
    monkeypatch.setattr(route, "DocumentEmbeddingService", MagicMock())

    @contextmanager
    def session_factory():
        yield fake_session

    route.run_reembed_job("job", session_factory=session_factory, config=config)
    adapter.close.assert_called_once()


# 验证自动解析链路创建的向量化客户端在作业结束后释放。
def test_auto_embedding_closes_owned_adapter(auth_db, model_settings, monkeypatch, tmp_path):
    from app.models.document_parsing import DocumentParseJob
    from app.services import document_parse_dispatcher as module
    from tests.auth_helpers import make_account
    from tests.document_parsing_helpers import SessionFactory, make_uploaded_file
    from tests.services.test_document_parse_dispatcher import FakeParser

    owner = make_account(auth_db)
    upload = make_uploaded_file(auth_db, tmp_path / "uploads", owner)
    job = DocumentParseJob(uploaded_file_id=upload.id, owner_user_id=owner.id)
    auth_db.add(job)
    auth_db.commit()
    service = MagicMock()
    monkeypatch.setattr(module, "get_settings", lambda: model_settings)
    monkeypatch.setattr(module, "make_document_embedding_service", lambda **kwargs: service)
    module.run_parse_job(
        job.id,
        session_factory=SessionFactory(auth_db),
        parser=FakeParser(),
        upload_storage_root=tmp_path / "uploads",
        artifact_storage_root=tmp_path / "parsed",
        document_chunking_enabled=True,
        document_embedding_enabled=True,
        chunking_service=MagicMock(),
    )
    service.adapter.close.assert_called_once()


# 验证改写策略覆盖超时时创建的临时连接，在模型调用失败后也会关闭。
def test_chat_timeout_override_releases_temporary_client(model_settings, monkeypatch):
    import pytest

    from app.services import chat_adapter as module
    from app.services.chat_config import ChatConfig

    temporary = MagicMock()
    temporary.chat.completions.create.side_effect = RuntimeError("unavailable")
    monkeypatch.setattr(module, "OpenAI", lambda **kwargs: temporary)
    adapter = module.ChatAdapter(
        config=ChatConfig.from_settings(model_settings), client=MagicMock()
    )
    with pytest.raises(module.ChatAPIError):
        adapter.generate([], request_timeout=1, max_retries=0)
    temporary.close.assert_called_once()


# 验证异步生成使用临时超时时，同样关闭失败调用的客户端。
def test_async_chat_timeout_override_releases_temporary_client(model_settings, monkeypatch):
    import asyncio

    import pytest

    from app.services import chat_adapter as module
    from app.services.chat_config import ChatConfig

    temporary = MagicMock()
    temporary.chat.completions.create = AsyncMock(side_effect=RuntimeError("unavailable"))
    temporary.close = AsyncMock()
    monkeypatch.setattr(module, "AsyncOpenAI", lambda **kwargs: temporary)
    adapter = module.ChatAdapter(
        config=ChatConfig.from_settings(model_settings), client=MagicMock()
    )
    with pytest.raises(module.ChatAPIError):
        asyncio.run(adapter.generate_async([], request_timeout=1, max_retries=0))
    temporary.close.assert_awaited_once()
