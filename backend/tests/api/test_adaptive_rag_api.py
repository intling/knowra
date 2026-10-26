"""自适应问答 HTTP RED：真实 Cookie、资料归属和额度，只替换模型与向量运算。"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlmodel import select

from app.api.deps import get_model_settings
from app.api.routes import search as routes
from app.core.config import get_settings
from app.main import app
from app.models.chat_quota import ChatUsage, UserChatLimit
from app.models.user import utc_now
from app.services.embedding_adapter import EmbeddingAPIError
from tests.auth_helpers import login_as, make_account, seed_knowledge_chain
from tests.search_helpers import (
    make_fake_chat_adapter,
    make_fake_chat_config,
    make_fake_embedding_adapter,
)


@pytest.fixture
def pipeline(auth_client, monkeypatch, fast_password_hasher):
    """不替换 SearchService 编排、认证或额度，避免测试只验证假的响应。"""
    embedding = make_fake_embedding_adapter()
    chat = make_fake_chat_adapter(content="这是使用通用知识给出的正常回答。")
    app.dependency_overrides.update(
        {
            get_model_settings: get_settings,
            routes.get_chat_config: lambda: make_fake_chat_config(),
            routes.get_embedding_adapter: lambda: embedding,
            routes.get_chat_adapter: lambda: chat,
            routes.get_query_rewriter: lambda: None,
            routes.get_search_response_cache: lambda: None,
            routes.get_search_audit_trail: lambda: None,
            routes.get_chat_circuit_breaker: lambda: None,
            routes.get_rerank_adapter: lambda: None,
        }
    )
    monkeypatch.setattr(routes.SearchService, "_vector_search", lambda *_args: [])
    return embedding, chat


def sign_in(client, session):
    """为每个用例建立独立账号和真实服务端会话。"""
    user = make_account(session)
    login_as(client, session, user)
    return user


def test_incomplete_generated_answer_releases_quota(auth_client, auth_db, pipeline):
    """验证非空截断正文返回不完整状态，真实额度预留释放，重试不被误扣限额。"""
    user = sign_in(auth_client, auth_db)
    auth_db.add(UserChatLimit(user_id=user.id, hourly_limit=1))
    auth_db.commit()
    pipeline[1].generate_async.return_value = SimpleNamespace(
        content="尚未解释完的正文",
        finish_reason="length",
        model="fixture",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
    )

    for _ in range(2):
        response = auth_client.post("/api/search", json={"query": "你好"})
        assert response.status_code == 200, response.text
        assert response.json().get("answer_incomplete") is True
        assert "尚未解释完的正文" in response.json()["answer"]
        assert auth_db.exec(select(ChatUsage)).all() == []


@pytest.mark.parametrize("query", ["你好", "Python 装饰器怎么使用？"])
def test_empty_library_question_returns_200_with_general_mode(
    auth_client, auth_db, pipeline, query
):
    """验证空知识库下普通问题得到 200、模型正文与模式，而不被路由统一转换为 404。"""
    sign_in(auth_client, auth_db)

    response = auth_client.post("/api/search", json={"query": query})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"] == "这是使用通用知识给出的正常回答。"
    assert body.get("answer_mode") == "general"
    assert body.get("retrieval_status") in ("skipped", "empty")
    assert body["results"] == []
    assert body["chat_model"] == "test-chat-model"
    assert body["answer_tokens"]["total_tokens"] == 150


@pytest.mark.parametrize("document_ids", [[], ["not-a-uuid"], [str(uuid4()) for _ in range(21)]])
def test_invalid_document_scope_has_field_reason_before_model_call(
    auth_client, auth_db, pipeline, document_ids
):
    """验证范围格式和数量错误返回具体 422，不静默丢弃参数后调用模型。"""
    sign_in(auth_client, auth_db)

    response = auth_client.post(
        "/api/search", json={"query": "总结这些资料的核心观点", "document_ids": document_ids}
    )

    assert response.status_code == 422, response.text
    errors = response.json()["detail"]
    assert any("document_ids" in error["loc"] and error["msg"] for error in errors)
    pipeline[1].generate_async.assert_not_called()


@pytest.mark.parametrize("scope_kind", ["foreign", "deleted", "missing"])
def test_invisible_document_scope_returns_same_safe_404(
    auth_client, auth_db, pipeline, tmp_path, scope_kind
):
    """验证他人、软删除与不存在的文档都被拒绝，响应不泄露归属且不进入模型。"""
    owner = sign_in(auth_client, auth_db)
    seed_knowledge_chain(auth_db, tmp_path / "visible", owner, vectors=1)
    if scope_kind == "missing":
        document_id = uuid4()
    else:
        user = make_account(auth_db) if scope_kind == "foreign" else owner
        upload, document, *_ = seed_knowledge_chain(auth_db, tmp_path / scope_kind, user, vectors=1)
        if scope_kind == "deleted":
            upload.deleted_at = utc_now()
            auth_db.add(upload)
            auth_db.commit()
        document_id = document.id

    response = auth_client.post(
        "/api/search",
        json={"query": "总结这些资料的核心观点", "document_ids": [str(document_id)]},
    )

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "指定资料不存在或不可访问，请重新选择资料"
    pipeline[1].generate_async.assert_not_called()


def test_selected_document_scope_reaches_real_summary_orchestration(
    auth_client, auth_db, pipeline, tmp_path
):
    """验证有效范围确实传入总结服务，提示词和来源不包含未选择的同用户文档。"""
    owner = sign_in(auth_client, auth_db)
    _upload, selected, *_ = seed_knowledge_chain(auth_db, tmp_path / "selected", owner, vectors=1)
    _other_upload, unselected, *_ = seed_knowledge_chain(
        auth_db, tmp_path / "unselected", owner, vectors=1
    )

    response = auth_client.post(
        "/api/search",
        json={"query": "总结这些资料的核心观点", "document_ids": [str(selected.id)]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("answer_mode") == "summary"
    assert {item["parsed_document_id"] for item in body["results"]} == {str(selected.id)}
    assert str(unselected.id) not in str(body["results"])
    assert body["summary_coverage"]["document_count"] == 1


def test_embedding_outage_is_not_reported_as_empty_library(auth_client, auth_db, pipeline):
    """验证 Embedding 故障可返回通用回答，但元信息明确说明检索不可用。"""
    sign_in(auth_client, auth_db)
    pipeline[0].embed_single.side_effect = EmbeddingAPIError("受控的嵌入服务故障")

    response = auth_client.post("/api/search", json={"query": "Python 装饰器怎么使用？"})

    assert response.status_code == 200, response.text
    assert response.json().get("answer_mode") == "general"
    assert response.json().get("retrieval_status") == "unavailable"


def test_document_scope_also_limits_regular_search_counts(auth_client, auth_db, pipeline, tmp_path):
    """验证范围不仅作用于总结，也限制普通资料问答的搜索数量，不统计未选中的资料。"""
    owner = sign_in(auth_client, auth_db)
    _upload, selected, *_ = seed_knowledge_chain(auth_db, tmp_path / "selected", owner, vectors=1)
    seed_knowledge_chain(auth_db, tmp_path / "outside", owner, vectors=2)

    response = auth_client.post(
        "/api/search",
        json={"query": "我的资料里的函数怎么使用？", "document_ids": [str(selected.id)]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["total_searched"] == 1, "文档范围必须同时限定检索空间和统计"


def test_successful_general_answer_counts_towards_chat_quota(auth_client, auth_db, pipeline):
    """验证通用回答同样消耗额度，达到上限后第二次在模型之前被拒绝。"""
    owner = sign_in(auth_client, auth_db)
    auth_db.add(UserChatLimit(user_id=owner.id, hourly_limit=1))
    auth_db.commit()

    first = auth_client.post("/api/search", json={"query": "你好"})

    assert first.status_code == 200, first.text
    assert first.json().get("answer_mode") == "general"
    second = auth_client.post("/api/search", json={"query": "再解释一个概念"})
    assert second.status_code == 429, second.text
    assert second.json()["code"] == "chat_quota_exceeded"
    assert "额度" in second.json()["detail"]
    assert int(second.headers["Retry-After"]) > 0
    assert pipeline[1].generate_async.await_count == 1


def test_summary_clarification_releases_chat_quota(auth_client, auth_db, pipeline):
    """验证没有资料时的澄清不消耗成功问答额度，用户仍能继续正常提问。"""
    owner = sign_in(auth_client, auth_db)
    auth_db.add(UserChatLimit(user_id=owner.id, hourly_limit=1))
    auth_db.commit()

    response = auth_client.post("/api/search", json={"query": "总结这些资料的核心观点"})

    assert response.status_code == 200, response.text
    assert response.json().get("answer_mode") == "clarification"
    usage = auth_db.exec(select(ChatUsage).where(ChatUsage.user_id == owner.id)).all()
    assert usage == [], "澄清不应保留本次成功问答额度占用"
    follow_up = auth_client.post("/api/search", json={"query": "你好"})
    assert follow_up.status_code == 200, follow_up.text


@pytest.mark.parametrize("query", ["你好", "总结这些资料的核心观点"])
def test_all_answer_modes_keep_authentication_boundary(auth_client, pipeline, query):
    """回归守护：通用回答和文档总结都必须先认证，不能新增匿名模型调用旁路。"""
    response = auth_client.post("/api/search", json={"query": query})

    assert response.status_code == 401, response.text
    assert response.json()["detail"]
    pipeline[1].generate_async.assert_not_called()


def test_unconfigured_chat_model_keeps_actionable_503(auth_client, auth_db, pipeline):
    """回归守护：自适应策略不能把缺少模型配置伪装成成功通用回答。"""
    sign_in(auth_client, auth_db)
    app.dependency_overrides[routes.get_chat_config] = lambda: make_fake_chat_config(model="")

    response = auth_client.post("/api/search", json={"query": "你好"})

    assert response.status_code == 503, response.text
    assert "配置" in response.json()["detail"]
    pipeline[1].generate_async.assert_not_called()
