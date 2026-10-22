"""问答入口额度 RED 测试：真实 Cookie/数据库，替换外部检索与模型。"""

import importlib
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlmodel import select

from app.api.routes import search as routes
from app.main import app
from app.schemas.search import SearchResponse
from app.services.embedding_adapter import EmbeddingAPIError
from tests.auth_helpers import login_as, make_account
from tests.search_helpers import make_fake_chat_config


@pytest.fixture
def search_pipeline(monkeypatch):
    # 只替换昂贵依赖与检索；额度、会话与权限仍执行真实服务逻辑。
    adapter_factory = MagicMock(return_value=object())
    response = SearchResponse(
        query="演示问题",
        query_embedding_preview=[0.1] * 5,
        embedding_model="fixture",
        embedding_dimensions=2560,
        top_k=5,
        total_searched=1,
        searched_document_count=1,
        search_time_ms=1,
        answer="来自资料的回答 [1]",
        chat_model="fixture",
    )
    search = MagicMock(return_value=response)
    monkeypatch.setattr(routes.SearchService, "search", search)
    monkeypatch.setattr(routes, "compute_fingerprint", lambda *a, **kw: "fixture-fingerprint")
    app.dependency_overrides.update(
        {
            routes.get_chat_config: lambda: make_fake_chat_config(),
            routes.get_embedding_adapter: lambda: adapter_factory(),
            routes.get_chat_adapter: lambda: object(),
            routes.get_query_rewriter: lambda: None,
            routes.get_search_response_cache: lambda: None,
            routes.get_search_audit_trail: lambda: None,
            routes.get_chat_circuit_breaker: lambda: None,
        }
    )
    yield search, adapter_factory, response


def configure_limit(session, user):
    limit_model = importlib.import_module("app.models.chat_quota").UserChatLimit
    session.add(limit_model(user_id=user.id, hourly_limit=3))
    session.commit()


def usage_rows(session):
    usage_model = importlib.import_module("app.models.chat_quota").ChatUsage
    return session.exec(select(usage_model)).all()


# 验证前三次正常响应不变，第 4 次在昂贵依赖前拒绝，错误码/中文原因/重试秒数完整。
def test_fourth_search_is_rejected_before_adapters(auth_client, auth_db, search_pipeline):
    user = make_account(auth_db)
    configure_limit(auth_db, user)
    login_as(auth_client, auth_db, user)
    search, adapter_factory, _ = search_pipeline
    for index in range(3):
        response = auth_client.post(
            "/api/search", json={"query": "演示问题", "session_id": str(index)}
        )
        assert response.status_code == 200, response.text
        assert response.json()["answer"] == "来自资料的回答 [1]"
    search.reset_mock()
    adapter_factory.reset_mock()

    response = auth_client.post("/api/search", json={"query": "演示问题", "session_id": "new-chat"})

    assert response.status_code == 429, response.text
    assert response.json()["code"] == "chat_quota_exceeded"
    assert "3" in response.json()["detail"] and "稍后" in response.json()["detail"]
    assert 1 <= int(response.headers["Retry-After"]) <= 3600
    search.assert_not_called()
    adapter_factory.assert_not_called()
    assert len(usage_rows(auth_db)) == 3


# 验证重新登录签发新的 Cookie 后额度保持，其他无限制成员仍可提问。
def test_new_login_does_not_reset_quota_and_other_user_is_unaffected(
    auth_client,
    auth_db,
    search_pipeline,
):
    user = make_account(auth_db)
    configure_limit(auth_db, user)
    login_as(auth_client, auth_db, user)
    for _ in range(3):
        assert auth_client.post("/api/search", json={"query": "问题"}).status_code == 200

    login_as(auth_client, auth_db, user)
    response = auth_client.post("/api/search", json={"query": "另一个线程"})
    assert response.status_code == 429, response.text
    assert response.json()["code"] == "chat_quota_exceeded"
    other = make_account(auth_db)
    login_as(auth_client, auth_db, other)
    for _ in range(4):
        assert auth_client.post("/api/search", json={"query": "问题"}).status_code == 200


# 验证参数错误仍返回明确 422，不扣额度且不调用模型。
def test_invalid_search_does_not_consume_quota(auth_client, auth_db, search_pipeline):
    user = make_account(auth_db)
    configure_limit(auth_db, user)
    login_as(auth_client, auth_db, user)

    response = auth_client.post("/api/search", json={"query": ""})

    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["msg"]
    assert usage_rows(auth_db) == []
    search_pipeline[0].assert_not_called()


# 验证检索或嵌入错误释放预留，反复失败后仍可以成功问答 3 次。
@pytest.mark.parametrize(
    "failure",
    [
        EmbeddingAPIError("fixture upstream timeout"),
        HTTPException(status_code=503, detail="fixture: 模型配置尚未就绪"),
    ],
)
def test_search_errors_release_reservation(auth_client, auth_db, search_pipeline, failure):
    user = make_account(auth_db)
    configure_limit(auth_db, user)
    login_as(auth_client, auth_db, user)
    search = search_pipeline[0]
    search.side_effect = failure
    for _ in range(4):
        response = auth_client.post("/api/search", json={"query": "问题"})
        assert response.status_code in {502, 503}, response.text
        assert response.json()["detail"]
        assert usage_rows(auth_db) == []
    search.side_effect = None
    for _ in range(3):
        assert auth_client.post("/api/search", json={"query": "问题"}).status_code == 200


# 验证依赖构造阶段失败也能清理预留，不能因尚未进入路由函数而扣次数。
def test_adapter_dependency_failure_releases_reservation(auth_client, auth_db, search_pipeline):
    user = make_account(auth_db)
    configure_limit(auth_db, user)
    login_as(auth_client, auth_db, user)
    search_pipeline[1].side_effect = HTTPException(
        status_code=503, detail="fixture: 嵌入服务不可用"
    )

    response = auth_client.post("/api/search", json={"query": "问题"})

    assert response.status_code == 503, response.text
    assert "嵌入服务不可用" in response.json()["detail"]
    assert usage_rows(auth_db) == []


# 验证没有资料和生成降级不扣次数，保留原来 404 或 200 降级响应及可读说明。
@pytest.mark.parametrize("kind", ["no_documents", "generation_failure"])
def test_empty_knowledge_or_generation_fallback_does_not_charge(
    auth_client,
    auth_db,
    search_pipeline,
    kind,
):
    user = make_account(auth_db)
    configure_limit(auth_db, user)
    login_as(auth_client, auth_db, user)
    response_fixture = search_pipeline[2]
    if kind == "no_documents":
        response_fixture.total_searched = 0
    else:
        response_fixture.generation_error = "fixture generation failed"
    for _ in range(4):
        response = auth_client.post("/api/search", json={"query": "问题"})
        assert response.status_code == (404 if kind == "no_documents" else 200), response.text
        payload = response.json()
        assert payload.get("detail") or payload.get("generation_error")
        assert usage_rows(auth_db) == []


# 验证无 Cookie 的请求必须保留应用认证边界，不运行检索或消耗额度。
def test_anonymous_search_is_still_unauthorized(auth_client, search_pipeline):
    response = auth_client.post("/api/search", json={"query": "问题"})

    assert response.status_code == 401, response.text
    assert response.json()["code"] == "auth_required"
    assert response.json()["detail"]
    search_pipeline[0].assert_not_called()


# 验证已到期的占用在下一次请求时恢复，无需整点、退出或清浏览器缓存。
def test_expired_usage_recovers_on_next_search(auth_client, auth_db, search_pipeline):
    user = make_account(auth_db)
    configure_limit(auth_db, user)
    login_as(auth_client, auth_db, user)
    for _ in range(3):
        assert auth_client.post("/api/search", json={"query": "问题"}).status_code == 200
    for row in usage_rows(auth_db):
        row.created_at = datetime.now(UTC) - timedelta(hours=1, seconds=1)
        auth_db.add(row)
    auth_db.commit()

    response = auth_client.post("/api/search", json={"query": "问题"})

    assert response.status_code == 200, response.text
    assert len(usage_rows(auth_db)) == 1
