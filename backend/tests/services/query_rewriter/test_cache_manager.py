"""CacheManager 单元测试 —— 会话绑定 L1 精确缓存。

测试覆盖：
- 会话绑定缓存：不同 session_id 的相同 query_hash 缓存隔离
- 精确匹配：相同 session_id + query_hash 命中
- TTL 过期：过期条目惰性淘汰
- LRU 淘汰：容量满时淘汰最久未使用条目
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from app.services.cache_manager import CacheManager
from app.services.query_rewriter import RewriteResult


# ── helpers ──────────────────────────────────────────────────────


def _make_result(original_query: str) -> RewriteResult:
    return RewriteResult(
        original_query=original_query,
        rewritten_queries=[{"query": original_query, "strategy": "direct"}],
    )


# ══════════════════════════════════════════════════════════
# 会话绑定缓存测试
# ══════════════════════════════════════════════════════════


class TestSessionScopedCache:
    """验证不同会话的缓存隔离。"""

    def test_different_sessions_same_query_independent_entries(self):
        """不同 session_id 的相同 query_hash 应独立存储/查找。"""
        cache = CacheManager(max_size=10)
        result_a = _make_result("query A")
        result_b = _make_result("query B")

        cache.store("session_a", "hash123", result_a)
        cache.store("session_b", "hash123", result_b)

        found_a = cache.lookup("session_a", "hash123")
        found_b = cache.lookup("session_b", "hash123")

        assert found_a is not None
        assert found_b is not None
        assert found_a.original_query == "query A"
        assert found_b.original_query == "query B"

    def test_same_session_same_hash_cache_hit(self):
        """同一 session_id + query_hash 命中缓存。"""
        cache = CacheManager(max_size=10)
        result = _make_result("test query")

        cache.store("sess", "hash456", result)
        found = cache.lookup("sess", "hash456")

        assert found is not None
        assert found.original_query == "test query"

    def test_different_session_no_cross_hit(self):
        """会话 A 存储的结果不应被会话 B 命中。"""
        cache = CacheManager(max_size=10)
        result = _make_result("private query")

        cache.store("session_a", "hash789", result)
        found = cache.lookup("session_b", "hash789")

        assert found is None

    def test_same_session_different_hash_miss(self):
        """同一会话中不同 query_hash 不会互相命中。"""
        cache = CacheManager(max_size=10)
        cache.store("sess", "hash_a", _make_result("query A"))

        found = cache.lookup("sess", "hash_b")
        assert found is None


# ══════════════════════════════════════════════════════════
# TTL 过期测试
# ══════════════════════════════════════════════════════════


class TestTTLExpiration:
    """验证缓存条目 TTL 过期。"""

    def test_expired_entry_returns_none(self, monkeypatch):
        """过期的缓存条目应返回 None。"""
        cache = CacheManager(max_size=10, ttl_seconds=0.01)
        result = _make_result("test")
        cache.store("sess", "hash", result)

        # 等待超过 TTL
        time.sleep(0.02)

        found = cache.lookup("sess", "hash")
        assert found is None

    def test_expired_entry_removed_from_store(self, monkeypatch):
        """过期的条目应从内部存储中移除。"""
        cache = CacheManager(max_size=10, ttl_seconds=0.01)
        cache.store("sess", "hash", _make_result("test"))

        time.sleep(0.02)
        cache.lookup("sess", "hash")

        assert cache.size == 0

    def test_unexpired_entry_still_valid(self):
        """未过期的条目正常返回。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)
        cache.store("sess", "hash", _make_result("test"))

        found = cache.lookup("sess", "hash")
        assert found is not None


# ══════════════════════════════════════════════════════════
# LRU 淘汰测试
# ══════════════════════════════════════════════════════════


class TestLRUEviction:
    """验证容量满时 LRU 淘汰。"""

    def test_evicts_least_recently_used_when_full(self):
        """容量满时淘汰最久未使用的条目。"""
        cache = CacheManager(max_size=3)

        cache.store("sess", "hash_a", _make_result("a"))
        cache.store("sess", "hash_b", _make_result("b"))
        cache.store("sess", "hash_c", _make_result("c"))

        # 访问 a（通过 store 更新将 a 移到 LRU 末尾）
        # store 已存在的键会将其移到 LRU 末尾
        cache.store("sess", "hash_a", _make_result("a"))

        # 存储 d → 淘汰 b（最久未使用）
        cache.store("sess", "hash_d", _make_result("d"))

        # 直接检查内部状态验证 LRU 淘汰结果。
        assert ("sess:hash_a" in cache._store)
        assert ("sess:hash_b" not in cache._store)
        assert ("sess:hash_c" in cache._store)
        assert ("sess:hash_d" in cache._store)

    def test_update_existing_moves_to_end(self):
        """更新已存在的键会将其移到 LRU 末尾。"""
        cache = CacheManager(max_size=2)

        cache.store("sess", "hash_a", _make_result("a"))
        cache.store("sess", "hash_b", _make_result("b"))

        # 更新 a → a 成为最近使用
        cache.store("sess", "hash_a", _make_result("a_v2"))

        # 存储 c → 淘汰 b
        cache.store("sess", "hash_c", _make_result("c"))

        assert cache.lookup("sess", "hash_a") is not None
        assert cache.lookup("sess", "hash_b") is None
        assert cache.lookup("sess", "hash_c") is not None


# ══════════════════════════════════════════════════════════
# 清理测试
# ══════════════════════════════════════════════════════════


class TestCacheClear:
    """验证缓存清理。"""

    def test_clear_removes_all_entries(self):
        """clear() 应移除所有缓存条目。"""
        cache = CacheManager(max_size=10)
        cache.store("sess_a", "hash_1", _make_result("a"))
        cache.store("sess_b", "hash_2", _make_result("b"))

        cache.clear()

        assert cache.size == 0
        assert cache.lookup("sess_a", "hash_1") is None
        assert cache.lookup("sess_b", "hash_2") is None


# ══════════════════════════════════════════════════════════
# 复合键测试
# ══════════════════════════════════════════════════════════


class TestCompositeKey:
    """验证复合缓存键格式。"""

    def test_composite_key_format(self):
        """复合键格式为 session_id:query_hash。"""
        key = CacheManager._make_composite_key("abc123", "def456")
        assert key == "abc123:def456"

    def test_composite_key_unique_per_session(self):
        """不同 session_id 产生不同的复合键。"""
        k1 = CacheManager._make_composite_key("sess_a", "hash")
        k2 = CacheManager._make_composite_key("sess_b", "hash")
        assert k1 != k2

    def test_composite_key_unique_per_hash(self):
        """不同 query_hash 产生不同的复合键。"""
        k1 = CacheManager._make_composite_key("sess", "hash_a")
        k2 = CacheManager._make_composite_key("sess", "hash_b")
        assert k1 != k2
