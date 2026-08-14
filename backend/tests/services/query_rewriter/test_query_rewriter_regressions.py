"""回归测试 —— 历史 review 问题的修复验证（Problem 1 / 2 / 3 / 4 / 5 / 6 / 7）。

本文件专门用于存放从以下文件迁移/补充的回归测试：

- ``test_search_service_rewrite.py`` → Problem 1: 缓存键包含对话历史摘要
- ``test_regressions.py``（补充）→ Problem 2: L1 响应缓存知识库指纹失效
- ``test_query_rewriter.py`` → Problem 3: Inflight 去重行为（threading.Event）
- ``test_query_rewriter_phase2.py`` → Problem 4: 并行执行保护词还原不覆盖 term_align 条目
- ``verify_review_issues.py`` → Problem 5: L2 语义缓存实为精确文本匹配
- ``verify_review_issues.py`` → Problem 6: 缺少 partial unique index 与 Alembic migration
- ``verify_review_issues.py`` → Problem 7: disabled 时 rewrite_info 仍非 null

每个回归测试对应一次已修复的 review issue，防止修复回退。
"""

from __future__ import annotations

import ast
import asyncio
import inspect
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.query_rewriter import QueryRewriter

from .conftest import build_phase2_rewriter


# ═══════════════════════════════════════════════════════════════════════════════
# 共享辅助函数（迁移自 test_search_service_rewrite.py）
# ═══════════════════════════════════════════════════════════════════════════════


def get_search_module():
    """Import the search service module."""
    return import_module("app.services.search")


def make_fake_embedding_adapter(*, vector_dims: int = 2560, model: str = "test-embed-model"):
    """Create a fake EmbeddingAdapter whose ``embed_single`` returns a canned vector."""

    class FakeEmbeddingResult:
        pass

    adapter = MagicMock()
    adapter.config = SimpleNamespace(model=model, dimensions=vector_dims)
    result = FakeEmbeddingResult()
    result.embedding = [0.1] * vector_dims
    adapter.embed_single = MagicMock(return_value=result)
    return adapter


def make_fake_chat_adapter(
    *,
    content: str = "根据文档内容，答案如下。",
    model: str = "test-chat-model",
):
    """Create a fake ChatAdapter whose ``generate_async`` returns a canned ChatResult."""
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
    """Build a fake ChatConfig with sensible test defaults."""
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


def make_fake_db_row(
    *,
    rank: int = 1,
    score: float = 0.123,
    chunk_id: uuid4 | None = None,
    parsed_document_id: uuid4 | None = None,
    document_name: str = "test-doc.pdf",
    sequence_index: int = 1,
    text: str = "这是测试分块文本内容。",
    contextualized_text: str = "上下文增强的测试分块文本。",
    token_count: int = 50,
    heading_path: list[str] | None = None,
    page_numbers: list[int] | None = None,
    dimensions: int = 2560,
    model: str = "test-embed-model",
):
    """Create a fake DB row as returned by a pgvector cosine-distance JOIN query."""
    chunk_id = chunk_id or uuid4()
    parsed_doc_id = parsed_document_id or uuid4()

    embedding = SimpleNamespace(
        id=uuid4(),
        chunk_id=chunk_id,
        parsed_document_id=parsed_doc_id,
        sequence_index=sequence_index,
        model=model,
        dimensions=dimensions,
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


def make_fake_session(rows: list | None = None, total_count: int | None = None):
    """Create a fake SQLModel Session."""
    session = MagicMock()
    if rows is None:
        rows = []
    if total_count is None:
        total_count = len(rows)

    mock_result = MagicMock()
    mock_result.all.return_value = rows
    mock_result.scalar.return_value = total_count
    mock_result.first.return_value = total_count
    session.exec.return_value = mock_result
    return session


# ═══════════════════════════════════════════════════════════════════════════════
# 共享 fixture 与辅助函数（迁移自 test_query_rewriter.py）
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_protector() -> MagicMock:
    """Mock ExactTermProtector —— 默认透传查询，无保护词。"""
    protector = MagicMock()
    protector.protect.return_value = ("test query", {})
    protector.restore.return_value = "test query"
    return protector


@pytest.fixture
def mock_cache_manager() -> MagicMock:
    """Mock CacheManager —— 默认缓存未命中。"""
    cache = MagicMock()
    cache.lookup.return_value = None
    return cache


@pytest.fixture
def mock_audit_trail() -> MagicMock:
    """Mock AuditTrail —— 静默记录，不做实际日志输出。"""
    return MagicMock()


@pytest.fixture
def mock_chat_adapter_fixture() -> MagicMock:
    """ChatAdapter mock fixture，避免与 conftest 命名冲突。"""
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


def _build_rewriter(
    protector=None,
    context_rewriter=None,
    cache_manager=None,
    chat_adapter=None,
    audit_trail=None,
    *,
    enabled: bool = True,
    pipeline_timeout: float = 3.0,
) -> QueryRewriter:
    """构建 QueryRewriter 实例的辅助函数。"""
    protector = protector or MagicMock()
    context_rewriter = context_rewriter or MagicMock()
    cache_manager = cache_manager or MagicMock()
    chat_adapter = chat_adapter or MagicMock()
    audit_trail = audit_trail or MagicMock()
    return QueryRewriter(
        exact_term_protector=protector,
        context_rewriter=context_rewriter,
        cache_manager=cache_manager,
        chat_adapter=chat_adapter,
        audit_trail=audit_trail,
        enabled=enabled,
        pipeline_timeout=pipeline_timeout,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 回归测试：缓存键包含对话历史摘要（Problem 1）
# ═══════════════════════════════════════════════════════════════════════════════


def test_different_histories_produce_different_cache_keys():
    """回归测试: 不同对话历史的相同查询不应命中同一响应缓存。

    Problem 1: 修复前 _make_search_cache_key 不包含 history_digest，
    相同 session_id + query + top_k 但不同 history 会命中同一缓存，
    导致不同对话上下文的用户收到相同的缓存响应。

    修复后: history_digest 纳入缓存键 → 不同 history 产生不同的缓存键。
    此测试通过验证不同 history 时 embed_single 被调用两次
    （而非一次缓存命中+一次嵌入）来证明缓存键正确分离。
    """
    module = get_search_module()

    rows = [make_fake_db_row(rank=1, score=0.10)]
    session = make_fake_session(rows=rows, total_count=1)
    embedding_adapter = make_fake_embedding_adapter()
    chat_adapter = make_fake_chat_adapter()
    chat_config = make_fake_chat_config()

    from app.services.cache_manager import CacheManager

    response_cache = CacheManager(max_size=100, ttl_seconds=600)

    session_id = "fixed-session-id"
    query = "档案怎么查？"
    top_k = 5

    history_a = [{"role": "user", "content": "蓝色档案怎么查？"}]
    history_b = [{"role": "user", "content": "红色档案怎么查？"}]

    # 不使用 query_rewriter（简化测试，只验证缓存键分离）
    service = module.SearchService(
        session=session,
        embedding_adapter=embedding_adapter,
        chat_adapter=chat_adapter,
        chat_config=chat_config,
        response_cache=response_cache,
    )

    # 首次请求：history_a
    response1 = service.search(
        query=query, top_k=top_k, history=history_a, session_id=session_id
    )
    assert response1.rewrite_info is None  # 无 query_rewriter

    # 第二次请求：history_b（不同 history，相同 query/top_k/session_id）
    response2 = service.search(
        query=query, top_k=top_k, history=history_b, session_id=session_id
    )
    assert response2.rewrite_info is None

    # 关键验证：embed_single 被调用了两次
    # 修复前（bug）：缓存键不包含 history，第二次请求命中第一次的缓存，
    #              embed_single 只被调用 1 次
    # 修复后：不同 history → 不同缓存键 → 两次都未命中缓存 → embed_single 被调用 2 次
    assert embedding_adapter.embed_single.call_count == 2, (
        f"修复前（bug）：如果缓存键不包含 history，第二次请求会命中缓存，"
        f"embed_single 只被调用 1 次。"
        f"修复后：不同 history 产生不同缓存键，embed_single 被调用 2 次。"
        f"实际调用次数: {embedding_adapter.embed_single.call_count}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 回归测试：L1 响应缓存知识库指纹失效（Problem 2）
# ═══════════════════════════════════════════════════════════════════════════════


def test_fingerprint_change_invalidates_response_cache():
    """回归测试: 知识库指纹变化后 L1 响应缓存应失效，避免返回软删除文档内容。

    Problem 2: 修复前 L1 响应缓存不校验知识库指纹，软删除文档后同一会话
    仍命中旧缓存，返回已删除来源。修复后 lookup() 校验指纹，不匹配时
    惰性淘汰并强制重新检索。

    此测试通过验证指纹变化后 embed_single 被再次调用（而非缓存命中）
    来证明缓存正确失效。
    """
    module = get_search_module()

    rows = [make_fake_db_row(rank=1, score=0.10)]
    session = make_fake_session(rows=rows, total_count=1)
    embedding_adapter = make_fake_embedding_adapter()
    chat_adapter = make_fake_chat_adapter()
    chat_config = make_fake_chat_config()

    from app.services.cache_manager import CacheManager

    response_cache = CacheManager(max_size=100, ttl_seconds=600)

    session_id = "fixed-session-id"
    query = "档案怎么查？"
    top_k = 5
    history = [{"role": "user", "content": "档案怎么查？"}]

    service = module.SearchService(
        session=session,
        embedding_adapter=embedding_adapter,
        chat_adapter=chat_adapter,
        chat_config=chat_config,
        response_cache=response_cache,
    )

    # 首次请求：指纹 fp-v1（文档尚在），结果写入缓存
    response_cache.update_fingerprint("fp-v1")
    service.search(query=query, top_k=top_k, history=history, session_id=session_id)

    # 模拟软删除文档 → route 层注入新的知识库指纹
    response_cache.update_fingerprint("fp-v2")

    # 第二次请求：相同 session/query/history，但指纹已变化
    service.search(query=query, top_k=top_k, history=history, session_id=session_id)

    # 关键验证：指纹变化后 embed_single 应被再次调用（缓存未命中）
    # 修复前（bug）：L1 不校验指纹 → 第二次命中旧缓存 → embed_single 只调用 1 次，
    #               软删除文档的内容会通过缓存返回。
    # 修复后：指纹不匹配 → 惰性淘汰 → 重新检索 → embed_single 调用 2 次。
    assert embedding_adapter.embed_single.call_count == 2, (
        f"修复前（bug）：如果 L1 不校验指纹，第二次请求会命中旧缓存，"
        f"embed_single 只被调用 1 次，软删除文档的内容会通过缓存返回。\n"
        f"修复后：指纹不匹配 → 惰性淘汰 → 重新检索，embed_single 被调用 2 次。\n"
        f"实际调用次数: {embedding_adapter.embed_single.call_count}"
    )


def test_invalidate_session_clears_stale_response_cache():
    """回归测试: 文档状态变更时应主动失效会话级 L1 响应缓存。

    Problem 2 的另一修复路径: 软删除不改变知识库指纹（指纹基于 embeddings
    数量与 job 时间戳，软删除仅设置 uploaded_files.deleted_at），因此仅靠
    指纹校验无法覆盖软删除场景。uploads 路由在 is_new/force 时调用
    invalidate_all_search_caches()，底层即 CacheManager.invalidate_session()。

    此测试验证 invalidate_session 正确移除会话条目，使后续查找 miss。
    """
    from app.services.cache_manager import CacheManager

    cache = CacheManager(max_size=100, ttl_seconds=600)

    # 写入同会话的多个条目（模拟缓存的搜索响应）
    cache.store("sess-1", "key-a", {"doc": "blue-review.txt"})
    cache.store("sess-1", "key-b", {"doc": "blue-review.txt"})
    cache.store("sess-2", "key-c", {"doc": "other.txt"})

    # 命中验证
    assert cache.lookup("sess-1", "key-a") is not None

    # 文档状态变更 → 主动失效 sess-1
    removed = cache.invalidate_session("sess-1")

    # 关键断言 1: 返回移除条目数
    assert removed == 2, (
        f"invalidate_session 应移除 sess-1 的 2 条 L1 条目，实际移除: {removed}"
    )

    # 关键断言 2: sess-1 的所有条目已清除 → 后续查找 miss
    assert cache.lookup("sess-1", "key-a") is None, (
        "修复前（bug）：文档状态变更未失效缓存，"
        "同一会话仍返回软删除文档的旧缓存内容。"
    )
    assert cache.lookup("sess-1", "key-b") is None

    # 关键断言 3: 其他会话不受影响
    assert cache.lookup("sess-2", "key-c") is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 回归测试：Inflight 去重行为（Problem 3）
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestInflightDedupBehavior:
    """验证并发相同查询通过 inflight 去重正确共享结果。

    Problem 3: 修复前使用 ``asyncio.Event`` 跨 event loop 不安全，
    同一个 event loop 内的并发 follower 可能永远收不到 ``set()`` 通知，
    导致超时后重复执行 LLM 调用。

    修复后使用 ``threading.Event`` + ``loop.run_in_executor()`` 实现
    跨线程/event loop 安全的 inflight 去重。
    """

    async def test_concurrent_rewrite_shares_result(
        self,
        mock_protector,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """两个并发 rewrite() 调用共享 leader 的重写结果。

        验证：
        - leader 和 follower 返回完全相同的 RewriteResult 对象
        - leader 的 _do_rewrite 中的 LLM 调用只执行一次
        - follower 不降级为 leader（不重复执行内部管线）
        """
        # 两阶段 barrier 精确控制并发时序：
        #   1. leader 进入 _do_rewrite 后设置 registered
        #   2. follower 此时发起请求，发现 inflight event 并等待
        #   3. 测试释放 continue，leader 完成
        barrier_registered = asyncio.Event()  # leader 已注册 inflight event
        barrier_continue = asyncio.Event()  # 测试释放以让 leader 完成

        mock_protector.protect.return_value = ("它怎么用", {})
        mock_protector.restore.side_effect = lambda query, term_map: query
        mock_cache_manager.lookup.return_value = None

        # 慢速 context_rewriter：在 _do_rewrite 内部阻塞，
        # 确保 leader 已注册 inflight event 且 follower 可以检测到
        slow_context = MagicMock()
        call_count = {"count": 0}

        async def slow_rewrite(query, history, model):
            call_count["count"] += 1
            barrier_registered.set()
            await barrier_continue.wait()
            return "Python 怎么用"

        slow_context.rewrite = slow_rewrite

        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=slow_context,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
        )

        # ── 启动 leader ──
        leader_task = asyncio.create_task(
            rewriter.rewrite("它怎么用", session_id="sess-1", history=[{"role": "user", "content": "Python 是什么"}])
        )

        # 等待 leader 注册 inflight event 并进入 _do_rewrite
        await asyncio.wait_for(barrier_registered.wait(), timeout=2.0)

        # ── 启动 follower ──（inflight event 已存在，应作为 follower 等待）
        follower_task = asyncio.create_task(
            rewriter.rewrite("它怎么用", session_id="sess-1", history=[{"role": "user", "content": "Python 是什么"}])
        )

        # 给 follower 时间进入 inflight 等待
        await asyncio.sleep(0.05)

        # ── 释放 leader 完成 ──
        barrier_continue.set()

        leader_result, follower_result = await asyncio.gather(
            leader_task, follower_task
        )

        # 关键断言 1：两个结果应为同一对象
        # （follower 通过 inflight dedup 获取 leader 的结果）
        assert leader_result is follower_result, (
            f"修复前（asyncio.Event）：follower 因等待超时或无法收到通知而降级为 "
            f"leader，产生两个不同的结果对象。\n"
            f"修复后（threading.Event + run_in_executor）：follower 正确获取 "
            f"leader 的同一结果对象。\n"
            f"leader_result id={id(leader_result)}, "
            f"follower_result id={id(follower_result)}"
        )

        # 关键断言 2：context_rewriter.rewrite() 只被调用一次
        # （只有 leader 执行 _do_rewrite，follower 不降级）
        assert call_count["count"] == 1, (
            f"修复前（asyncio.Event）：follower 等待超时后降级为 leader，"
            f"context_rewriter.rewrite() 被调用 2 次。\n"
            f"修复后：follower 正确获取 leader 结果，"
            f"context_rewriter.rewrite() 只被调用 1 次。\n"
            f"实际调用次数: {call_count['count']}"
        )

        # 关键断言 3：结果内容正确
        assert leader_result.original_query == "它怎么用"
        assert leader_result.rewritten_queries[0]["query"] == "Python 怎么用"

    async def test_different_dedup_keys_run_independently(
        self,
        mock_protector,
        mock_cache_manager,
        mock_chat_adapter_fixture,
        mock_audit_trail,
    ):
        """不同 dedup key 的并发请求应独立执行，互不干扰。

        验证：
        - 不同 session_id → 不同 dedup key → 各自作为 leader 执行
        - context_rewriter.rewrite() 被调用 2 次
        """
        mock_protector.protect.return_value = ("它怎么用", {})
        mock_protector.restore.side_effect = lambda query, term_map: query
        mock_cache_manager.lookup.return_value = None

        call_count = {"count": 0}

        # 快 context rewriter（无需 barrier，因为不同 key 互不干扰）
        fast_context = MagicMock()

        def fast_rewrite(query, history, model):
            call_count["count"] += 1
            return f"{query}（来自 sess-{call_count['count']} 改写）"

        fast_context.rewrite = fast_rewrite

        rewriter = _build_rewriter(
            protector=mock_protector,
            context_rewriter=fast_context,
            cache_manager=mock_cache_manager,
            chat_adapter=mock_chat_adapter_fixture,
            audit_trail=mock_audit_trail,
        )

        # 两个不同 session_id → 不同 dedup key → 各自独立执行
        r1, r2 = await asyncio.gather(
            rewriter.rewrite("它怎么用", session_id="sess-a", history=[{"role": "user", "content": "hi"}]),
            rewriter.rewrite("它怎么用", session_id="sess-b", history=[{"role": "user", "content": "hi"}]),
        )

        # 不同 dedup key → context_rewriter 被调用 2 次
        assert call_count["count"] == 2, (
            f"不同 dedup key 应各自作为 leader 独立执行，"
            f"context_rewriter.rewrite() 应被调用 2 次。"
            f"实际调用次数: {call_count['count']}"
        )

        # 各自的结果应不同（因为不同的 session 产生了不同的改写）
        assert r1 is not r2, "不同 dedup key 的结果不应是同一对象"
        assert r1.rewritten_queries[0]["query"] != r2.rewritten_queries[0]["query"]


# ═══════════════════════════════════════════════════════════════════════════════
# 回归测试：并行执行保护词还原不覆盖 term_align 条目（Problem 4）
# ═══════════════════════════════════════════════════════════════════════════════


class TestParallelProtectRestoreRegression:
    """验证并行 normalize+term_align 执行后保护词还原的正确性。

    Problem 4: 修复前 protection restore 使用 ``strategy_rewrites[-1]``
    更新主策略条目。并行场景下 ``-1`` 是 term_align 条目（而非 normalize），
    导致 term_align 的改写结果被 protect.restore 结果覆盖丢失。

    修复后: 使用 ``primary_strategy_index`` 追踪 normalize 条目索引，
    protection restore 仅更新 normalize 条目，term_align 结果完整保留。
    """

    pytestmark = pytest.mark.asyncio

    async def test_parallel_execution_preserves_term_align_query_after_restore(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_term_align_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """并行执行后 protect.restore 仅更新 normalize 条目，term_align 不受影响。

        场景:
        - 查询包含需要保护的专业术语
        - 策略路由返回 normalize + term_align → 触发并行执行
        - protect.restore 返回与 normalize 原始输出不同的还原结果
        - 验证 normalize 条目被正确更新，term_align 条目保持原样
        """
        # ── 设置保护词（在 protect/restore 之间产生不同查询）──
        mock_protector_phase2.protect.return_value = (
            "如何学习 PYTHON-TOKEN",
            {"PYTHON-TOKEN": "Python"},
        )
        # restore 返回还原后的完整查询（与 normalize 原始输出不同）
        mock_protector_phase2.restore.return_value = "如何学习 Python 编程语言"

        # ── 路由到 normalize + term_align ──
        mock_strategy_router.route.return_value = {
            "intent": "analytical",
            "complexity": 5,
            "strategies": ["normalize", "term_align"],
        }

        # normalize 返回带保护词的查询（稍后由 restore 还原）
        mock_normalize_rewriter.rewrite.return_value = {
            "query": "如何系统学习 PYTHON-TOKEN",
            "strategy": "normalize",
            "duration_ms": 120.0,
            "tokens": 50,
        }
        # term_align 返回术语对齐后的查询（应完全保留，不被覆盖）
        mock_term_align_rewriter.rewrite.return_value = {
            "query": "如何学习 Python（术语对齐版）",
            "strategy": "term_align",
            "duration_ms": 80.0,
            "tokens": 35,
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            term_align_rewriter=mock_term_align_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
            pipeline_timeout=30.0,  # 确保预算充足（≥16s 触发并行路径）
            strategy_timeout=15.0,
        )

        result = await rewriter.rewrite("如何学习", history=None)

        # ── 按策略名称索引查询结果 ──
        queries_by_strategy: dict[str, str] = {}
        for rq in result.rewritten_queries:
            queries_by_strategy[rq["strategy"]] = rq["query"]

        # ── 断言 1: 两个策略条目都存在 ──
        assert "normalize" in queries_by_strategy, (
            f"normalize 策略条目缺失，rewritten_queries={result.rewritten_queries}"
        )
        assert "term_align" in queries_by_strategy, (
            f"term_align 策略条目缺失，rewritten_queries={result.rewritten_queries}"
        )

        # ── 断言 2: rewritten_queries[0] 是 normalize（主策略优先）──
        assert result.rewritten_queries[0]["strategy"] == "normalize", (
            f"主策略（normalize）应位于 rewritten_queries[0]，"
            f"实际首位策略: {result.rewritten_queries[0]['strategy']}"
        )

        # ── 断言 3: normalize 条目已通过 protect.restore 更新 ──
        # 修复后: primary_strategy_index 指向 normalize，restore 更新 normalize 条目
        normalize_query = queries_by_strategy["normalize"]
        assert normalize_query == "如何学习 Python 编程语言", (
            f"protect.restore 应更新 normalize 条目为其还原结果。\n"
            f"预期: '如何学习 Python 编程语言'（restore 返回）\n"
            f"实际: '{normalize_query}'"
        )

        # ── 断言 4 (核心): term_align 条目保持原始查询，未被 protect.restore 覆盖 ──
        # 修复前（bug）：strategy_rewrites[-1]["query"] = final_query
        #   → strategy_rewrites[-1] 在并行场景是 term_align 条目
        #   → term_align 的 "如何学习 Python（术语对齐版）" 被覆盖为 restore 结果
        # 修复后：_update_idx = primary_strategy_index
        #   → 只有 normalize 条目被更新，term_align 保持其原始输出
        term_align_query = queries_by_strategy["term_align"]
        assert term_align_query == "如何学习 Python（术语对齐版）", (
            f"修复前（bug）：strategy_rewrites[-1] 在并行场景指向 term_align，\n"
            f"  protect.restore 的返回结果 "
            f"'如何学习 Python 编程语言' 会覆盖 term_align 条目，\n"
            f"  原始 term_align 输出 "
            f"'如何学习 Python（术语对齐版）' 永久丢失。\n"
            f"修复后：primary_strategy_index 追踪 normalize 条目，\n"
            f"  term_align 条目完整保留。\n"
            f"实际 term_align 查询: '{term_align_query}'"
        )

        # ── 断言 5: strategies_used 包含两个策略 ──
        assert "normalize" in result.strategies_used
        assert "term_align" in result.strategies_used

    async def test_serial_execution_protect_restore_updates_last_strategy(
        self,
        mock_protector_phase2,
        mock_strategy_router,
        mock_normalize_rewriter,
        mock_cache_manager_with_l2,
        mock_audit_trail_phase2,
    ):
        """对比测试：串行场景下 protect.restore 更新最后一个策略条目（正常行为）。

        当只有一个 normalize 策略时（无并行），strategy_rewrites[-1] == primary_strategy_index，
        两种实现方式结果相同。此测试确认串行场景不受修复影响。
        """
        mock_protector_phase2.protect.return_value = (
            "OPTION-TOKEN 配置",
            {"OPTION-TOKEN": "Nginx"},
        )
        mock_protector_phase2.restore.return_value = "Nginx 配置教程"

        mock_strategy_router.route.return_value = {
            "intent": "procedural",
            "complexity": 3,
            "strategies": ["normalize"],  # 仅一个策略，无并行
        }

        mock_normalize_rewriter.rewrite.return_value = {
            "query": "OPTION-TOKEN 配置教程",
            "strategy": "normalize",
            "duration_ms": 100.0,
            "tokens": 40,
        }

        rewriter = build_phase2_rewriter(
            protector=mock_protector_phase2,
            strategy_router=mock_strategy_router,
            normalize_rewriter=mock_normalize_rewriter,
            cache_manager=mock_cache_manager_with_l2,
            audit_trail=mock_audit_trail_phase2,
            pipeline_timeout=30.0,
        )

        result = await rewriter.rewrite("配置", history=None)

        # 单个策略 → rewritten_queries 只有一项
        assert len(result.rewritten_queries) == 1
        assert result.rewritten_queries[0]["strategy"] == "normalize"
        # protect.restore 更新 normalize 条目
        assert result.rewritten_queries[0]["query"] == "Nginx 配置教程"


# ═══════════════════════════════════════════════════════════════════════════════
# 回归测试：L2 语义缓存实为精确文本匹配（Problem 5）
# ═══════════════════════════════════════════════════════════════════════════════


def test_l2_is_exact_text_match_not_semantic():
    """回归测试: L2 缓存是规范化文本的精确匹配，而非向量语义检索。

    Problem 5: 修复前 lookup_l2 用 ``_normalize_text`` + 精确字典查询，
    却宣称 ``similarity: 1.0`` 的语义命中。OpenSpec 要求向量余弦距离
    ≤ 0.05 才命中，但当前实现没有 embedding 或余弦计算。

    修复后（本 PR 降级为诚实精确缓存）: 删除虚假 similarity 声明，
    文档标注为"规范化文本精确匹配"。语义相似但文字不同的查询应 miss
    —— 这是被接受的降级行为，向量语义检索规划为后续迭代。
    """
    from app.services.cache_manager import CacheManager

    cache = CacheManager(max_size=10, ttl_seconds=300)

    # 存储"如何办理退款？"
    cache.store_l2("如何办理退款？", "退款流程结果 A")

    # 语义相似但文字不同的查询 → 必然 miss（精确文本匹配）
    result = cache.lookup_l2("退款流程是什么？")
    assert result is None, (
        f"修复前（虚假宣称）：语义缓存应命中同义句。\n"
        f"修复后（诚实降级）：L2 为规范化文本精确匹配，"
        f"'退款流程是什么？' 与 '如何办理退款？' 文字不同，必然 miss。\n"
        f"实际结果: {result}"
    )


def test_l2_lookup_returns_no_similarity_field():
    """回归测试: lookup_l2 不再返回伪造的 ``similarity`` 字段。

    Problem 5 的另一修复点: 精确匹配实现的 lookup_l2 不应宣称
    ``similarity: 1.0``（那是向量余弦检索才有的语义）。修复后返回
    dict 仅含 result / knowledge_type / source_session_id 三个字段。
    """
    from app.services.cache_manager import CacheManager

    cache = CacheManager(max_size=10, ttl_seconds=300)

    cache.store_l2("如何办理退款？", "退款流程结果")

    result = cache.lookup_l2("如何办理退款？")

    assert result is not None, "规范化文本完全一致时应命中"
    assert "similarity" not in result, (
        f"修复前（bug）：lookup_l2 返回固定 similarity=1.0，"
        f"虚假宣称语义命中。\n"
        f"修复后：精确文本匹配不返回 similarity 字段，"
        f"向量语义检索规划为后续迭代。\n"
        f"实际返回键: {sorted(result.keys())}"
    )
    assert result["result"] == "退款流程结果"
    assert result["knowledge_type"] == "general_knowledge"


def test_l2_normalized_exact_match_hits_across_whitespace_case():
    """回归测试: L2 精确匹配经规范化后对大小写/空白不敏感（正向验证）。

    验证降级后的精确缓存仍保留其价值——标准化查询可跨会话复用，
    规范化（trim + 小写 + 单空格化）后文本一致即命中。
    """
    from app.services.cache_manager import CacheManager

    cache = CacheManager(max_size=10, ttl_seconds=300)

    cache.store_l2("  How  To   Refund  ", "退款流程结果")

    # 规范化后文本一致（trim + 小写 + 单空格化）→ 命中
    result = cache.lookup_l2("how to refund")

    assert result is not None, (
        "规范化（trim + lowercase + 单空格化）后文本一致，应命中"
    )
    assert result["result"] == "退款流程结果"


# ═══════════════════════════════════════════════════════════════════════════════
# 回归测试：partial unique index 与 Alembic migration（Problem 6）
# ═══════════════════════════════════════════════════════════════════════════════


def test_dedup_index_is_partial_unique():
    """回归测试: ix_uploaded_files_dedup 应为 partial unique index。

    Problem 6: 修复前该索引是普通复合索引（非 unique），``create_upload()``
    是 select-then-insert，并发上传同一文件可插入重复记录。修复后模型声明
    ``unique=True`` + ``postgresql_where=(deleted_at IS NULL)``，保证同一用户
    下未软删除记录唯一，同时允许多条已删除记录共存。
    """
    from app.models.uploaded_file import UploadedFile

    found = False
    for arg in UploadedFile.__table_args__:
        if getattr(arg, "name", None) == "ix_uploaded_files_dedup":
            found = True
            assert arg.unique, (
                f"修复前（bug）：ix_uploaded_files_dedup 为普通索引（unique=False），"
                f"无法防止并发重复插入。\n"
                f"修复后：应为 unique index，当前 unique={arg.unique}。"
            )
            where_clause = arg.dialect_kwargs.get("postgresql_where")
            assert where_clause is not None, (
                f"修复前（bug）：缺少 partial 约束，软删除后同一 checksum 无法重新上传。\n"
                f"修复后：应有 WHERE deleted_at IS NULL partial 约束。"
            )
            break

    assert found, "未找到 ix_uploaded_files_dedup 索引"


def test_create_upload_handles_integrity_error():
    """回归测试: create_upload 应有 IntegrityError 处理实现并发幂等。

    Problem 6 的另一修复点: 保留 select-then-insert 快速路径，但在唯一索引
    触发 IntegrityError 时捕获并转为读取已存在记录，闭合竞态窗口。
    """
    from app.services.uploads import UploadService

    source = inspect.getsource(UploadService.create_upload)

    assert "IntegrityError" in source, (
        f"修复前（bug）：create_upload 仅 select-then-insert，"
        f"并发上传同一文件会插入重复记录。\n"
        f"修复后：应捕获 IntegrityError 转为读取已存在记录。"
    )
    assert "_find_active_duplicate" in source, (
        "create_upload 应先查后插（_find_active_duplicate）作为快速路径"
    )


def test_dedup_migration_exists():
    """回归测试: ix_uploaded_files_dedup 已出现在 Alembic migration 中。

    Problem 6: 修复前模型改了索引但没有 migration，fresh upgrade 后真实 DB
    无该索引。修复后 migration 删除旧普通索引并创建 partial unique index。
    """
    alembic_dir = Path(__file__).resolve().parents[3] / "alembic" / "versions"
    migration_files = list(alembic_dir.glob("*.py"))

    assert len(migration_files) > 0, "应有 Alembic migration 文件"

    found = False
    for mf in migration_files:
        content = mf.read_text(encoding="utf-8")
        if "ix_uploaded_files_dedup" in content and "unique=True" in content:
            found = True
            break

    assert found, (
        f"修复前（bug）：模型改了索引但没有 migration，"
        f"`alembic upgrade head` 后真实 DB 无 partial unique index。\n"
        f"修复后：migration 应包含 ix_uploaded_files_dedup 且 unique=True。"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 回归测试：disabled 时 rewrite_info 仍非 null（Problem 7）
# ═══════════════════════════════════════════════════════════════════════════════


def test_rewrite_info_field_nullable():
    """回归测试: SearchResponse.rewrite_info 应为 Optional（可返回 null）。

    Problem 7: 修复前 schema 用 ``default_factory`` 使 rewrite_info 始终非 null，
    disabled 时前端渲染空 RewritePanel。修复后类型为 ``RewriteInfo | None``，
    default 为 None，disabled/failure 路径返回 null。
    """
    from app.schemas.search import SearchResponse

    rewrite_field = SearchResponse.model_fields["rewrite_info"]

    annotation_str = str(rewrite_field.annotation)
    assert "None" in annotation_str or "NoneType" in annotation_str, (
        f"修复前（bug）：rewrite_info 非 Optional，disabled 时仍返回空对象。\n"
        f"修复后：应为 Optional[RewriteInfo]，当前 annotation: {annotation_str}"
    )
    assert rewrite_field.default is None, (
        f"修复后 rewrite_info default 应为 None（禁用时返回 null），"
        f"实际: {rewrite_field.default}"
    )


def test_disabled_path_creates_null_rewrite_info():
    """回归测试: search.py 的 disabled 路径应赋值 ``rewrite_info = None``。

    Problem 7: 修复前 disabled 路径仍构造非 null 的 RewriteInfo（含空列表），
    修复后 disabled 路径返回 None，与成功/失败路径（仍构造 RewriteInfo）区分。
    """
    search_py = Path(__file__).resolve().parents[3] / "app" / "services" / "search.py"
    source = search_py.read_text(encoding="utf-8")

    # 成功/失败路径仍构造 RewriteInfo
    rewrite_assignments = [
        line.strip()
        for line in source.split("\n")
        if "rewrite_info = RewriteInfo(" in line
    ]
    assert len(rewrite_assignments) >= 2, (
        f"预期至少 2 条 rewrite_info = RewriteInfo(...) 赋值（成功/失败路径），"
        f"实际: {rewrite_assignments}"
    )

    # disabled 路径应有 rewrite_info = None
    none_assignments = [
        line.strip()
        for line in source.split("\n")
        if line.strip().startswith("rewrite_info = None")
    ]
    assert len(none_assignments) >= 1, (
        f"修复前（bug）：disabled 路径返回非 null 的 RewriteInfo，"
        f"前端显示空重写面板。\n"
        f"修复后：disabled 路径应赋值 rewrite_info = None。"
        f"实际发现 None 赋值: {none_assignments}"
    )


def test_disabled_comment_says_returns_null():
    """回归测试: 代码注释确认 disabled 时返回 null 的设计意图。

    修复后 search.py 的 disabled 分支注释明确说明"未配置重写时返回 null，
    前端据此区分功能未启用与重写尝试但无产出"。
    """
    search_py = Path(__file__).resolve().parents[3] / "app" / "services" / "search.py"
    source = search_py.read_text(encoding="utf-8")

    assert "未配置重写时返回 null" in source, (
        "修复后 search.py 注释应说明 disabled 时返回 null 的设计意图"
    )
