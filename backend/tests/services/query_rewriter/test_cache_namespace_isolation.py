"""用户体系红测试：QueryRewriter 按 cache_namespace 隔离 L1、L2 与在途去重。

SearchService 以 ``u:{user_id}:{kb_fingerprint}`` 作为命名空间调用重写器；
不同用户即使 query、history、session_id 完全相同，也不得共享任何重写缓存或在途结果。
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from app.services.cache_manager import CacheManager
from app.services.query_rewriter import QueryRewriter

HISTORY = [{"role": "user", "content": "Python 是什么"}]


def build_rewriter(cache_manager, context_rewriter=None) -> QueryRewriter:
    protector = MagicMock()
    protector.protect.side_effect = lambda query: (query, {})
    protector.restore.side_effect = lambda query, term_map: query
    if context_rewriter is None:
        context_rewriter = MagicMock()
        context_rewriter.rewrite.side_effect = lambda query, history, model: f"{query}（已融合）"
    return QueryRewriter(
        exact_term_protector=protector,
        context_rewriter=context_rewriter,
        cache_manager=cache_manager,
        chat_adapter=MagicMock(),
        audit_trail=MagicMock(),
        enabled=True,
        pipeline_timeout=3.0,
    )


# 验证 L1：相同 session_id/history/query 但不同命名空间不会命中；同命名空间再次请求命中 L1。
@pytest.mark.asyncio
async def test_l1_cache_is_isolated_by_namespace() -> None:
    cache = CacheManager(ttl_seconds=60)
    rewriter = build_rewriter(cache)

    first = await rewriter.rewrite(
        "它怎么用", session_id="shared", history=HISTORY, cache_namespace="u:A:fp"
    )
    other_user = await rewriter.rewrite(
        "它怎么用", session_id="shared", history=HISTORY, cache_namespace="u:B:fp"
    )
    same_user = await rewriter.rewrite(
        "它怎么用", session_id="shared", history=HISTORY, cache_namespace="u:A:fp"
    )

    assert first.cache_hit is False
    assert other_user.cache_hit is False, "其他用户不得命中 L1 重写缓存"
    assert same_user.cache_hit is True
    assert same_user.cache_level == "L1"


# 验证 L2：用户 A 写入的跨会话语义缓存，对用户 B 不可见；A 的其他会话仍可命中。
@pytest.mark.asyncio
async def test_l2_cache_is_isolated_by_namespace() -> None:
    cache = CacheManager(ttl_seconds=60)
    rewriter = build_rewriter(cache)

    await rewriter.rewrite("如何配置 Nginx 反向代理", session_id="a-1", cache_namespace="u:A:fp")
    other_user = await rewriter.rewrite(
        "如何配置 Nginx 反向代理", session_id="b-1", cache_namespace="u:B:fp"
    )
    same_user = await rewriter.rewrite(
        "如何配置 Nginx 反向代理", session_id="a-2", cache_namespace="u:A:fp"
    )

    assert other_user.cache_level != "L2", "其他用户不得命中 L2 语义缓存"
    assert same_user.cache_level == "L2"


# 验证 L2 查询与写入都携带命名空间参数。
@pytest.mark.asyncio
async def test_l2_lookup_and_store_receive_namespace() -> None:
    cache = MagicMock()
    cache.lookup.return_value = None
    cache.lookup_l2.return_value = None
    rewriter = build_rewriter(cache)

    await rewriter.rewrite("如何配置 Nginx 反向代理", cache_namespace="u:A:fp")

    assert cache.lookup_l2.call_args.kwargs.get("namespace") == "u:A:fp"
    assert cache.store_l2.called
    assert all(call.kwargs.get("namespace") == "u:A:fp" for call in cache.store_l2.call_args_list)


# 验证在途去重按命名空间隔离：A 的请求仍在执行时，B 的相同请求必须独立执行而非复用 A 的结果。
@pytest.mark.asyncio
async def test_inflight_dedup_is_isolated_by_namespace() -> None:
    registered = asyncio.Event()
    release = asyncio.Event()
    calls = {"count": 0}

    async def slow_rewrite(query, history, model):
        calls["count"] += 1
        registered.set()
        await release.wait()
        return f"{query}（第 {calls['count']} 次融合）"

    context = MagicMock()
    context.rewrite = slow_rewrite
    cache = MagicMock()
    cache.lookup.return_value = None
    cache.lookup_l2.return_value = None
    rewriter = build_rewriter(cache, context)

    leader = asyncio.create_task(
        rewriter.rewrite("它怎么用", history=HISTORY, cache_namespace="u:A:fp")
    )
    await asyncio.wait_for(registered.wait(), timeout=2.0)
    other_user = asyncio.create_task(
        rewriter.rewrite("它怎么用", history=HISTORY, cache_namespace="u:B:fp")
    )
    await asyncio.sleep(0.05)
    release.set()
    result_a, result_b = await asyncio.gather(leader, other_user)

    assert calls["count"] == 2, "不同用户的相同请求必须各自执行重写管线"
    assert result_a is not result_b


# 验证 CacheManager 的 L2 命名空间：不同命名空间互不可见，未带命名空间的旧调用看不到命名空间条目。
def test_cache_manager_l2_namespace_isolation() -> None:
    cache = CacheManager(ttl_seconds=60)
    cache.store_l2("如何配置 Nginx", {"q": "A"}, namespace="u:A:fp")

    assert cache.lookup_l2("如何配置 Nginx", namespace="u:B:fp") is None
    assert cache.lookup_l2("如何配置 Nginx") is None
    hit = cache.lookup_l2("如何配置 Nginx", namespace="u:A:fp")
    assert hit is not None
    assert hit["result"] == {"q": "A"}
