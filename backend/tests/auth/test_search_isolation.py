# 用户体系红测试：检索、搜索响应缓存与知识库指纹的用户隔离。
# pgvector 余弦距离无法在 SQLite 执行，向量检索的作用域通过编译后的 SQL 断言；
# 计数、指纹与“当前用户无数据”的 HTTP 行为使用真实 SQLite 数据验证。

from collections.abc import Generator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlmodel import Session

from app.main import app
from app.services.cache_manager import CacheManager
from app.services.kb_fingerprint import compute_fingerprint
from app.services.query_rewriter import RewriteResult
from app.services.search import SearchService
from tests.auth_helpers import login_as, make_account, seed_knowledge_chain
from tests.search_helpers import (
    make_fake_chat_adapter,
    make_fake_chat_config,
    make_fake_db_row,
    make_fake_embedding_adapter,
    make_fake_session,
)


def make_service(owner_user_id, *, session=None, fingerprint="fp-1", **kwargs) -> SearchService:
    return SearchService(
        session=session or make_fake_session(rows=[make_fake_db_row(rank=1, score=0.1)]),
        owner_user_id=owner_user_id,
        kb_fingerprint=fingerprint,
        embedding_adapter=kwargs.pop("embedding_adapter", make_fake_embedding_adapter()),
        chat_adapter=kwargs.pop("chat_adapter", make_fake_chat_adapter()),
        chat_config=make_fake_chat_config(),
        similarity_threshold=0,
        min_score_threshold=0,
        **kwargs,
    )


def compiled_sql(statement) -> tuple[str, dict]:
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled), dict(compiled.params)


# ── SearchService 作用域 ─────────────────────────────────────────────────


# 验证 SearchService 必须显式传入 owner_user_id，没有用户就无法构造检索服务。
def test_search_service_requires_owner_user_id() -> None:
    with pytest.raises(TypeError):
        SearchService(
            session=make_fake_session(),
            embedding_adapter=make_fake_embedding_adapter(),
            chat_adapter=make_fake_chat_adapter(),
            chat_config=make_fake_chat_config(),
        )


# 验证计数与向量检索 SQL 都按当前用户过滤 embedding/解析文档/上传文件，并排除软删除上传。
def test_count_and_vector_search_are_scoped_to_owner() -> None:
    owner_id = uuid4()
    session = make_fake_session(rows=[make_fake_db_row(rank=1, score=0.1)])
    service = make_service(owner_id, session=session)

    service.search(query="私有问题", top_k=3)

    statements = [call.args[0] for call in session.exec.call_args_list]
    assert len(statements) >= 2, "检索至少应执行计数和向量检索两条 SQL"
    for statement in statements[:2]:
        sql, params = compiled_sql(statement)
        assert "document_embeddings.owner_user_id" in sql, sql
        assert "uploaded_files.owner_user_id" in sql, sql
        assert "uploaded_files.deleted_at IS NULL" in sql, sql
        assert owner_id in params.values(), f"SQL 参数中缺少当前用户 ID：{params}"
    vector_sql, _ = compiled_sql(statements[1])
    assert "parsed_documents.owner_user_id" in vector_sql


# 验证真实数据下计数只统计当前用户且源文件未软删除的向量。
def test_count_total_embeddings_counts_only_visible_owner_vectors(
    auth_db: Session, tmp_path
) -> None:
    alice = make_account(auth_db)
    bob = make_account(auth_db)
    seed_knowledge_chain(auth_db, tmp_path / "a", alice, vectors=2)
    deleted_upload, *_ = seed_knowledge_chain(auth_db, tmp_path / "a2", alice, vectors=3)
    deleted_upload.deleted_at = datetime.now(UTC)
    auth_db.add(deleted_upload)
    auth_db.commit()
    seed_knowledge_chain(auth_db, tmp_path / "b", bob, vectors=4)

    assert make_service(alice.id, session=auth_db)._count_total_embeddings() == 2
    assert make_service(bob.id, session=auth_db)._count_total_embeddings() == 4


# 验证当前用户没有向量时仍能生成通用回答，不暴露他人向量数或资料。
def test_user_without_vectors_gets_empty_response_even_if_others_have_data(
    auth_db: Session, tmp_path
) -> None:
    alice = make_account(auth_db)
    bob = make_account(auth_db)
    seed_knowledge_chain(auth_db, tmp_path / "a", alice, vectors=2)
    chat_adapter = make_fake_chat_adapter()

    response = make_service(bob.id, session=auth_db, chat_adapter=chat_adapter).search(
        query="Alice 的私有片段", top_k=5
    )

    assert response.total_searched == 0
    assert response.results == []
    chat_adapter.generate_async.assert_awaited_once()
    assert response.answer_mode == "general"


# 验证两个用户使用相同 session_id、query、history 时不会命中对方的搜索响应缓存；同用户仍可命中。
def test_response_cache_is_isolated_per_user() -> None:
    cache = CacheManager(ttl_seconds=60)
    alice_id, bob_id = uuid4(), uuid4()
    history = [{"role": "user", "content": "上一轮"}]
    alice_embed = make_fake_embedding_adapter()
    bob_embed = make_fake_embedding_adapter()

    make_service(alice_id, response_cache=cache, embedding_adapter=alice_embed).search(
        query="同一个问题", top_k=5, history=history, session_id="shared-session"
    )
    make_service(bob_id, response_cache=cache, embedding_adapter=bob_embed).search(
        query="同一个问题", top_k=5, history=history, session_id="shared-session"
    )
    make_service(alice_id, response_cache=cache, embedding_adapter=alice_embed).search(
        query="同一个问题", top_k=5, history=history, session_id="shared-session"
    )

    assert bob_embed.embed_single.call_count == 1, "Bob 不得命中 Alice 的缓存响应"
    assert alice_embed.embed_single.call_count == 1, "同一用户同一会话的第二次请求应命中缓存"


# 验证同一用户的知识库指纹变化后旧缓存不再命中。
def test_response_cache_key_includes_kb_fingerprint() -> None:
    cache = CacheManager(ttl_seconds=60)
    owner_id = uuid4()
    embed = make_fake_embedding_adapter()

    make_service(
        owner_id, response_cache=cache, fingerprint="fp-old", embedding_adapter=embed
    ).search(query="问题", top_k=5, session_id="s1")
    make_service(
        owner_id, response_cache=cache, fingerprint="fp-new", embedding_adapter=embed
    ).search(query="问题", top_k=5, session_id="s1")

    assert embed.embed_single.call_count == 2


# 验证 SearchService 调用查询重写时传入按用户和指纹划分的 cache_namespace。
def test_query_rewriter_receives_user_scoped_namespace() -> None:
    owner_id = uuid4()
    rewriter = type("FakeRewriter", (), {})()
    calls: list[dict] = []

    def rewrite(query, **kwargs):
        calls.append(kwargs)
        return RewriteResult(original_query=query, rewritten_queries=[{"query": query}])

    rewriter.rewrite = rewrite
    make_service(owner_id, query_rewriter=rewriter, fingerprint="fp-9").search(
        query="问题", top_k=5, session_id="s1"
    )
    make_service(owner_id, query_rewriter=rewriter, fingerprint="fp-9").search(
        query="问题", top_k=5
    )

    assert calls[0]["cache_namespace"] == f"u:{owner_id}:fp-9:adaptive-v1:docs:all"
    assert calls[0]["session_id"] == "s1"
    assert calls[1]["cache_namespace"] == f"u:{owner_id}:fp-9:adaptive-v1:docs:all", (
        "即使没有 session_id 与 history，也必须传入用户命名空间，保证去重与 L2 按用户隔离"
    )


# ── 知识库指纹 ───────────────────────────────────────────────────────────


# 验证指纹只聚合当前用户的数据：他人新增向量不改变我的指纹，我新增向量会改变。
def test_compute_fingerprint_is_scoped_to_owner(auth_db: Session, tmp_path) -> None:
    alice = make_account(auth_db)
    bob = make_account(auth_db)
    alice_before = compute_fingerprint(auth_db, owner_user_id=alice.id)
    bob_before = compute_fingerprint(auth_db, owner_user_id=bob.id)
    assert alice_before == bob_before, "空知识库指纹应稳定一致"

    seed_knowledge_chain(auth_db, tmp_path / "b", bob, vectors=2)

    assert compute_fingerprint(auth_db, owner_user_id=alice.id) == alice_before
    assert compute_fingerprint(auth_db, owner_user_id=bob.id) != bob_before


# ── HTTP 检索路由 ────────────────────────────────────────────────────────


@pytest.fixture
def search_overrides() -> Generator[dict]:
    from app.api.routes import search as search_routes

    fake_rewriter = type("FakeRewriter", (), {})()
    fake_rewriter.calls = []
    fake_rewriter.update_fingerprint_calls = []

    def rewrite(query, **kwargs):
        fake_rewriter.calls.append(kwargs)
        return RewriteResult(original_query=query, rewritten_queries=[{"query": query}])

    fake_rewriter.rewrite = rewrite
    fake_rewriter.update_fingerprint = fake_rewriter.update_fingerprint_calls.append
    response_cache = CacheManager(ttl_seconds=60)
    chat_adapter = make_fake_chat_adapter()
    app.dependency_overrides.update(
        {
            search_routes.get_chat_config: lambda: make_fake_chat_config(),
            search_routes.get_embedding_adapter: lambda: make_fake_embedding_adapter(),
            search_routes.get_chat_adapter: lambda: chat_adapter,
            search_routes.get_query_rewriter: lambda: fake_rewriter,
            search_routes.get_search_response_cache: lambda: response_cache,
        }
    )
    yield {"rewriter": fake_rewriter, "cache": response_cache, "chat": chat_adapter}


# 验证 HTTP 检索：他人有数据而当前用户没有时返回通用回答且不暴露他人资料，
# 且路由不再写入进程级共享指纹，重写命名空间绑定当前用户。
def test_search_route_scopes_to_current_user(
    auth_client: TestClient, auth_db: Session, search_overrides: dict, tmp_path
) -> None:
    alice = make_account(auth_db)
    bob = make_account(auth_db)
    seed_knowledge_chain(auth_db, tmp_path / "a", alice, vectors=2)
    login_as(auth_client, auth_db, bob)

    response = auth_client.post("/api/search", json={"query": "Alice 的私有片段", "top_k": 5})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_searched"] == 0
    assert body["results"] == []
    assert body["answer_mode"] == "general"
    search_overrides["chat"].generate_async.assert_awaited_once()
    messages = search_overrides["chat"].generate_async.call_args.args[0]
    assert all("secret" not in message["content"] for message in messages)
    rewriter = search_overrides["rewriter"]
    assert rewriter.calls and rewriter.calls[0]["cache_namespace"].startswith(f"u:{bob.id}:")
    assert rewriter.update_fingerprint_calls == [], "路由不得再写入进程级共享指纹"
    assert search_overrides["cache"].fingerprint is None
