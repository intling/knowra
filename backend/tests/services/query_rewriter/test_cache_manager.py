"""CacheManager 单元测试 —— 会话绑定 L1 精确缓存。

测试覆盖：
- 会话绑定缓存：不同 session_id 的相同 query_hash 缓存隔离
- 精确匹配：相同 session_id + query_hash 命中
- TTL 过期：过期条目惰性淘汰
- LRU 淘汰：容量满时淘汰最久未使用条目
"""

from __future__ import annotations

import time

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
        assert "sess:hash_a" in cache._store
        assert "sess:hash_b" not in cache._store
        assert "sess:hash_c" in cache._store
        assert "sess:hash_d" in cache._store

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


# ══════════════════════════════════════════════════════════
# ttl_override 参数测试
# ══════════════════════════════════════════════════════════


class TestTTLOverride:
    """验证 store() / store_l2() 的 ttl_override 参数。"""

    def test_store_ttl_override_shorter(self, monkeypatch):
        """ttl_override 短于默认 TTL 时，条目应提前过期。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)  # 默认 1 小时
        cache.store("sess", "hash", _make_result("test"), ttl_override=0.01)

        time.sleep(0.02)
        found = cache.lookup("sess", "hash")
        assert found is None

    def test_store_ttl_override_longer_than_default(self):
        """ttl_override 长于默认 TTL 时，条目有效期应更长。"""
        cache = CacheManager(max_size=10, ttl_seconds=0.01)
        cache.store("sess", "hash", _make_result("test"), ttl_override=3600)

        # 默认 TTL 0.01s 已过期，但 ttl_override=3600 应保持条目存活
        time.sleep(0.02)
        found = cache.lookup("sess", "hash")
        assert found is not None
        assert found.original_query == "test"

    def test_store_ttl_override_none_uses_default(self, monkeypatch):
        """ttl_override=None 时回退到实例默认 TTL。"""
        cache = CacheManager(max_size=10, ttl_seconds=0.01)
        cache.store("sess", "hash", _make_result("test"), ttl_override=None)

        time.sleep(0.02)
        found = cache.lookup("sess", "hash")
        assert found is None

    def test_per_entry_independent_ttl(self, monkeypatch):
        """不同条目可以有独立的 TTL，互不影响。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)

        # 条目 A：短 TTL
        cache.store("sess", "hash_a", _make_result("a"), ttl_override=0.01)
        # 条目 B：长 TTL
        cache.store("sess", "hash_b", _make_result("b"), ttl_override=3600)

        time.sleep(0.02)

        # A 已过期，B 仍有效
        assert cache.lookup("sess", "hash_a") is None
        assert cache.lookup("sess", "hash_b") is not None
        assert cache.lookup("sess", "hash_b").original_query == "b"

    def test_store_l2_ttl_override(self, monkeypatch):
        """store_l2() 的 ttl_override 应独立控制 L2 条目 TTL。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)
        cache.store_l2(
            "test query",
            _make_result("test"),
            knowledge_type="context_dependent",
            ttl_override=0.01,
        )

        time.sleep(0.02)
        found = cache.lookup_l2("test query")
        assert found is None

    def test_store_l2_ttl_override_longer(self):
        """store_l2() 的 ttl_override 长于默认时保持条目存活。"""
        cache = CacheManager(max_size=10, ttl_seconds=0.01)
        cache.store_l2(
            "test query",
            _make_result("test"),
            knowledge_type="general_knowledge",
            ttl_override=3600,
        )

        time.sleep(0.02)
        found = cache.lookup_l2("test query")
        assert found is not None
        assert found["knowledge_type"] == "general_knowledge"

    def test_store_l2_ttl_override_none_uses_default(self, monkeypatch):
        """store_l2() 的 ttl_override=None 时回退到实例默认 TTL。"""
        cache = CacheManager(max_size=10, ttl_seconds=0.01)
        cache.store_l2(
            "test query",
            _make_result("test"),
            knowledge_type="general_knowledge",
            ttl_override=None,
        )

        time.sleep(0.02)
        found = cache.lookup_l2("test query")
        assert found is None

    def test_l1_l2_independent_ttl(self, monkeypatch):
        """L1 和 L2 缓存的 TTL 互不影响。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)

        # L1: 短 TTL，L2: 长 TTL
        cache.store("sess", "hash", _make_result("l1"), ttl_override=0.01)
        cache.store_l2(
            "test query",
            _make_result("l2"),
            knowledge_type="general_knowledge",
            ttl_override=3600,
        )

        time.sleep(0.02)

        # L1 过期，L2 仍有效
        assert cache.lookup("sess", "hash") is None
        found_l2 = cache.lookup_l2("test query")
        assert found_l2 is not None
        assert found_l2["knowledge_type"] == "general_knowledge"


# ══════════════════════════════════════════════════════════
# 统计计数器测试
# ══════════════════════════════════════════════════════════


class TestStatsCounters:
    """验证缓存统计计数器正确递增。"""

    def test_hits_counter_increments_on_cache_hit(self):
        """缓存命中时 hits 计数器应递增。"""
        cache = CacheManager(max_size=10)
        cache.store("sess", "hash", _make_result("test"))
        cache.lookup("sess", "hash")  # 命中

        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 0

    def test_misses_counter_increments_on_not_found(self):
        """未找到条目时 misses 计数器应递增。"""
        cache = CacheManager(max_size=10)
        cache.lookup("sess", "nonexistent")

        stats = cache.get_stats()
        assert stats["misses"] == 1
        assert stats["hits"] == 0

    def test_expirations_counter_increments_on_ttl_expiry(self):
        """TTL 过期时 expirations 和 misses 计数器应同时递增。"""
        cache = CacheManager(max_size=10, ttl_seconds=0.01)
        cache.store("sess", "hash", _make_result("test"))

        time.sleep(0.02)
        cache.lookup("sess", "hash")  # 过期

        stats = cache.get_stats()
        assert stats["expirations"] == 1
        assert stats["misses"] == 1  # 过期也算一次 miss

    def test_evictions_counter_increments_on_lru_eviction(self):
        """LRU 淘汰时 evictions 计数器应递增。"""
        cache = CacheManager(max_size=2)
        cache.store("sess", "hash_a", _make_result("a"))
        cache.store("sess", "hash_b", _make_result("b"))
        cache.store("sess", "hash_c", _make_result("c"))  # 淘汰 hash_a

        stats = cache.get_stats()
        assert stats["evictions"] == 1

    def test_l2_hits_counter_increments(self):
        """L2 命中时 l2_hits 计数器应递增。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)
        cache.store_l2("test query", _make_result("test"), knowledge_type="general_knowledge")
        cache.lookup_l2("test query")  # 命中

        stats = cache.get_stats()
        assert stats["l2_hits"] == 1
        assert stats["l2_misses"] == 0

    def test_l2_misses_counter_increments(self):
        """L2 未命中时 l2_misses 计数器应递增。"""
        cache = CacheManager(max_size=10)
        cache.lookup_l2("nonexistent")

        stats = cache.get_stats()
        assert stats["l2_misses"] == 1
        assert stats["l2_hits"] == 0

    def test_l2_expirations_increments_both_counters(self):
        """L2 TTL 过期时 expirations 和 l2_misses 应同时递增。"""
        cache = CacheManager(max_size=10, ttl_seconds=0.01)
        cache.store_l2("test query", _make_result("test"), knowledge_type="general_knowledge")

        time.sleep(0.02)
        cache.lookup_l2("test query")  # 过期

        stats = cache.get_stats()
        assert stats["expirations"] >= 1
        assert stats["l2_misses"] == 1

    def test_multiple_operations_accumulate_counters(self):
        """多次操作后计数器应正确累加。"""
        cache = CacheManager(max_size=10)
        cache.store("sess", "hash_a", _make_result("a"))
        cache.store("sess", "hash_b", _make_result("b"))

        cache.lookup("sess", "hash_a")  # hit
        cache.lookup("sess", "hash_a")  # hit
        cache.lookup("sess", "hash_c")  # miss
        cache.lookup("sess", "hash_d")  # miss

        stats = cache.get_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 2


# ══════════════════════════════════════════════════════════
# get_stats() 快照测试
# ══════════════════════════════════════════════════════════


class TestGetStats:
    """验证 get_stats() 统计快照。"""

    def test_get_stats_returns_all_expected_keys(self):
        """get_stats() 应返回所有预期的统计键。"""
        cache = CacheManager(max_size=10)
        stats = cache.get_stats()

        expected_keys = {
            "hits", "misses", "l2_hits", "l2_misses",
            "evictions", "expirations", "sweep_removed",
            "fingerprint_mismatches", "l2_fingerprint_mismatches",
            "size", "l2_size", "hit_rate",
        }
        assert set(stats.keys()) == expected_keys

    def test_hit_rate_is_zero_when_no_lookups(self):
        """无任何查找时 hit_rate 应为 0.0。"""
        cache = CacheManager(max_size=10)
        stats = cache.get_stats()
        assert stats["hit_rate"] == 0.0

    def test_hit_rate_all_hits(self):
        """全部命中时 hit_rate 应为 1.0。"""
        cache = CacheManager(max_size=10)
        cache.store("sess", "hash", _make_result("test"))
        cache.lookup("sess", "hash")
        cache.lookup("sess", "hash")

        stats = cache.get_stats()
        assert stats["hit_rate"] == 1.0

    def test_hit_rate_mixed(self):
        """混合命中/未命中时 hit_rate 应正确计算。"""
        cache = CacheManager(max_size=10)
        cache.store("sess", "hash_a", _make_result("a"))
        cache.lookup("sess", "hash_a")  # hit
        cache.lookup("sess", "hash_b")  # miss

        stats = cache.get_stats()
        assert stats["hit_rate"] == 0.5

    def test_size_reflects_current_store(self):
        """size 和 l2_size 应反映当前缓存条目数。"""
        cache = CacheManager(max_size=10)
        cache.store("sess", "hash_a", _make_result("a"))
        cache.store("sess", "hash_b", _make_result("b"))
        cache.store_l2("query", _make_result("test"))

        stats = cache.get_stats()
        assert stats["size"] == 2
        assert stats["l2_size"] == 1

    def test_expired_entries_affect_hit_rate(self):
        """过期条目应计为 miss，影响 hit_rate。"""
        cache = CacheManager(max_size=10, ttl_seconds=0.01)
        cache.store("sess", "hash", _make_result("test"))

        time.sleep(0.02)
        cache.lookup("sess", "hash")  # 过期 → miss

        stats = cache.get_stats()
        assert stats["hit_rate"] == 0.0
        assert stats["misses"] == 1


# ══════════════════════════════════════════════════════════
# 写入时抽样清理测试
# ══════════════════════════════════════════════════════════


class TestSweepExpired:
    """验证 _sweep_expired / _maybe_sweep 写入时抽样清理。"""

    def test_sweep_removes_expired_l1_entries(self):
        """_sweep_expired 应移除 L1 中的过期条目。"""
        cache = CacheManager(max_size=10, ttl_seconds=0.01)
        cache.store("sess", "hash_a", _make_result("a"))
        cache.store("sess", "hash_b", _make_result("b"))

        time.sleep(0.02)

        removed = cache._sweep_expired(cache._store, "l1")
        assert removed == 2
        assert cache.size == 0

    def test_sweep_removes_expired_l2_entries(self):
        """_sweep_expired 应移除 L2 中的过期条目。"""
        cache = CacheManager(max_size=10, ttl_seconds=0.01)
        cache.store_l2("query a", _make_result("a"))
        cache.store_l2("query b", _make_result("b"))

        time.sleep(0.02)

        removed = cache._sweep_expired(cache._l2_store, "l2")
        assert removed == 2
        assert cache.l2_size == 0

    def test_sweep_preserves_unexpired_entries(self):
        """_sweep_expired 不应移除未过期的条目。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)
        cache.store("sess", "hash_a", _make_result("a"))
        cache.store("sess", "hash_b", _make_result("b"))

        removed = cache._sweep_expired(cache._store, "l1")
        assert removed == 0
        assert cache.size == 2

    def test_sweep_empty_store_returns_zero(self):
        """空存储的 _sweep_expired 应返回 0。"""
        cache = CacheManager(max_size=10)
        removed = cache._sweep_expired(cache._store, "l1")
        assert removed == 0

    def test_sweep_increments_sweep_removed_stat(self):
        """清理过期条目后 sweep_removed 计数器应递增。"""
        cache = CacheManager(max_size=10, ttl_seconds=0.01)
        cache.store("sess", "hash_a", _make_result("a"))
        cache.store("sess", "hash_b", _make_result("b"))

        time.sleep(0.02)
        cache._sweep_expired(cache._store, "l1")

        stats = cache.get_stats()
        assert stats["sweep_removed"] == 2

    def test_sweep_only_samples_up_to_limit(self):
        """条目数超过抽样上限时只检查随机样本。"""
        cache = CacheManager(max_size=100, ttl_seconds=0.01)

        # 存储 100 条已过期的条目
        for i in range(100):
            cache.store("sess", f"hash_{i}", _make_result(f"test_{i}"))

        time.sleep(0.02)

        removed = cache._sweep_expired(cache._store, "l1")
        # 抽样上限为 20，所以最多移除 20 条
        assert 0 < removed <= 20

    def test_maybe_sweep_triggers_at_correct_interval(self, monkeypatch):
        """_maybe_sweep 应在每 N 次写入时触发。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)

        # 将 CLEANUP_TRIGGER_EVERY_N 设为 3，方便测试
        monkeypatch.setattr(CacheManager, "_CLEANUP_TRIGGER_EVERY_N", 3)

        sweep_counts = []
        original_sweep = cache._sweep_expired

        def tracking_sweep(store, label):
            result = original_sweep(store, label)
            sweep_counts.append(result)
            return result

        monkeypatch.setattr(cache, "_sweep_expired", tracking_sweep)

        # 写入第 1、2 次 → 不触发
        cache.store("sess", "hash_a", _make_result("a"))
        cache.store("sess", "hash_b", _make_result("b"))
        assert len(sweep_counts) == 0

        # 写入第 3 次 → 触发（两次 _sweep_expired 调用：l1 + l2）
        cache.store("sess", "hash_c", _make_result("c"))
        assert len(sweep_counts) == 2

        # 写入第 4、5 次 → 不触发
        cache.store("sess", "hash_d", _make_result("d"))
        cache.store("sess", "hash_e", _make_result("e"))
        assert len(sweep_counts) == 2

        # 写入第 6 次 → 触发
        cache.store("sess", "hash_f", _make_result("f"))
        assert len(sweep_counts) == 4

    def test_sweep_mixed_expired_and_unexpired(self):
        """混合过期/未过期条目时只移除过期的。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)

        # 短 TTL 条目
        cache.store("sess", "hash_expired", _make_result("expired"), ttl_override=0.01)
        # 长 TTL 条目
        cache.store("sess", "hash_valid", _make_result("valid"), ttl_override=3600)

        time.sleep(0.02)

        removed = cache._sweep_expired(cache._store, "l1")
        assert removed == 1
        assert cache.size == 1
        assert cache.lookup("sess", "hash_valid") is not None


# ══════════════════════════════════════════════════════════
# 统计快照日志测试
# ══════════════════════════════════════════════════════════


class TestMaybeLogStats:
    """验证 _maybe_log_stats 定期统计快照输出。"""

    def test_logs_at_interval(self, monkeypatch, caplog):
        """距上次日志超过间隔时应输出统计快照。"""
        cache = CacheManager(max_size=10)
        # 设置极短的日志间隔
        monkeypatch.setattr(CacheManager, "_STATS_LOG_INTERVAL", 0.0)

        with caplog.at_level("INFO"):
            cache.store("sess", "hash", _make_result("test"))

        snapshot_logs = [r for r in caplog.records if r.name == "app.services.cache_manager"]
        # 应该有一条 cache_stats_snapshot 日志
        assert len(snapshot_logs) == 1
        assert "cache_stats_snapshot" in snapshot_logs[0].msg or "cache_stats_snapshot" in str(snapshot_logs[0].msg)

    def test_does_not_log_too_frequently(self, monkeypatch, caplog):
        """日志间隔未到时不应重复输出。"""
        cache = CacheManager(max_size=10)
        # 设置很长的日志间隔
        monkeypatch.setattr(CacheManager, "_STATS_LOG_INTERVAL", 999999.0)

        with caplog.at_level("INFO"):
            cache.store("sess", "hash_a", _make_result("a"))
            cache.store("sess", "hash_b", _make_result("b"))
            cache.store("sess", "hash_c", _make_result("c"))

        snapshot_logs = [r for r in caplog.records if r.name == "app.services.cache_manager"]
        assert len(snapshot_logs) == 0  # 间隔未到，不应输出

    def test_stats_snapshot_contains_expected_fields(self, monkeypatch, caplog):
        """统计快照日志应包含所有必要字段。"""
        cache = CacheManager(max_size=10)
        monkeypatch.setattr(CacheManager, "_STATS_LOG_INTERVAL", 0.0)

        with caplog.at_level("INFO"):
            cache.store("sess", "hash", _make_result("test"))
            cache.lookup("sess", "hash")

        snapshot_logs = [r for r in caplog.records if r.name == "app.services.cache_manager"]
        assert len(snapshot_logs) >= 1
        # structlog 将 event_dict 渲染为字符串存入 record.msg
        msg = snapshot_logs[0].msg
        for key in ("hits", "misses", "size", "hit_rate"):
            assert key in msg, f"Expected '{key}' in log message: {msg}"

    def test_last_stats_log_updated_after_logging(self, monkeypatch):
        """日志输出后 _last_stats_log 应更新为当前时间。"""
        cache = CacheManager(max_size=10)
        monkeypatch.setattr(CacheManager, "_STATS_LOG_INTERVAL", 0.0)

        old_timestamp = cache._last_stats_log
        cache._maybe_log_stats()
        new_timestamp = cache._last_stats_log

        assert new_timestamp > old_timestamp


# ══════════════════════════════════════════════════════════
# 知识库指纹校验测试（模块三）
# ══════════════════════════════════════════════════════════


class TestFingerprintValidation:
    """验证 L1 缓存的指纹感知校验。"""

    def test_fingerprint_match_cache_hit(self):
        """指纹匹配时缓存正常命中。"""
        cache = CacheManager(max_size=10)
        cache.update_fingerprint("fp_v1")
        cache.store("sess", "hash", _make_result("test"))

        found = cache.lookup("sess", "hash")
        assert found is not None
        assert found.original_query == "test"

    def test_fingerprint_mismatch_cache_miss(self):
        """指纹不匹配时缓存应视为 miss。"""
        cache = CacheManager(max_size=10)
        cache.update_fingerprint("fp_v1")
        cache.store("sess", "hash", _make_result("test"))

        # 改变指纹
        cache.update_fingerprint("fp_v2")
        found = cache.lookup("sess", "hash")
        assert found is None

    def test_fingerprint_mismatch_removes_entry(self):
        """指纹不匹配时应从存储中移除旧条目。"""
        cache = CacheManager(max_size=10)
        cache.update_fingerprint("fp_v1")
        cache.store("sess", "hash", _make_result("test"))

        cache.update_fingerprint("fp_v2")
        cache.lookup("sess", "hash")

        assert cache.size == 0

    def test_fingerprint_mismatch_increments_counter(self):
        """指纹不匹配时 fingerprint_mismatches 计数器应递增。"""
        cache = CacheManager(max_size=10)
        cache.update_fingerprint("fp_v1")
        cache.store("sess", "hash", _make_result("test"))

        cache.update_fingerprint("fp_v2")
        cache.lookup("sess", "hash")

        stats = cache.get_stats()
        assert stats["fingerprint_mismatches"] == 1
        assert stats["misses"] == 1

    def test_no_fingerprint_set_all_hits_pass(self):
        """未设置指纹时（向后兼容），所有查找应正常通过。"""
        cache = CacheManager(max_size=10)
        cache.store("sess", "hash", _make_result("test"))

        found = cache.lookup("sess", "hash")
        assert found is not None
        assert found.original_query == "test"

    def test_fingerprint_none_and_stored_none_compatible(self):
        """指纹为 None 且存储条目也无指纹时，正常命中。"""
        cache = CacheManager(max_size=10)
        cache.update_fingerprint(None)
        cache.store("sess", "hash", _make_result("test"))

        found = cache.lookup("sess", "hash")
        assert found is not None

    def test_update_fingerprint_none_disables_validation(self):
        """设置 fingerprint 为 None 后禁用校验。"""
        cache = CacheManager(max_size=10)
        cache.update_fingerprint("fp_v1")
        cache.store("sess", "hash", _make_result("test"))
        cache.update_fingerprint("fp_v2")
        # 先确认 fp_v2 会让旧条目失败
        assert cache.lookup("sess", "hash") is None

        # 重新存入 fp_v1 的条目
        cache.update_fingerprint("fp_v1")
        cache.store("sess", "hash", _make_result("test"))

        # 设为 None → 禁用校验
        cache.update_fingerprint(None)
        found = cache.lookup("sess", "hash")
        assert found is not None

    def test_multiple_entries_different_fingerprints(self):
        """同时存储不同指纹的条目，匹配当前指纹的应命中。"""
        cache = CacheManager(max_size=10)

        cache.update_fingerprint("fp_v1")
        cache.store("sess", "hash_a", _make_result("v1_a"))
        cache.store("sess", "hash_b", _make_result("v1_b"))

        cache.update_fingerprint("fp_v2")
        cache.store("sess", "hash_c", _make_result("v2_c"))

        # 当前指纹为 fp_v2，v1 的条目不应命中
        assert cache.lookup("sess", "hash_a") is None
        assert cache.lookup("sess", "hash_b") is None
        assert cache.lookup("sess", "hash_c") is not None
        assert cache.lookup("sess", "hash_c").original_query == "v2_c"


class TestL2FingerprintValidation:
    """验证 L2 语义缓存的指纹感知校验。"""

    def test_l2_fingerprint_match_cache_hit(self):
        """L2 指纹匹配时正常返回。"""
        cache = CacheManager(max_size=10)
        cache.update_fingerprint("fp_v1")
        cache.store_l2("test query", _make_result("test"),
                       knowledge_type="general_knowledge")

        found = cache.lookup_l2("test query")
        assert found is not None
        assert found["knowledge_type"] == "general_knowledge"

    def test_l2_fingerprint_mismatch_cache_miss(self):
        """L2 指纹不匹配时应返回 None。"""
        cache = CacheManager(max_size=10)
        cache.update_fingerprint("fp_v1")
        cache.store_l2("test query", _make_result("test"),
                       knowledge_type="general_knowledge")

        cache.update_fingerprint("fp_v2")
        found = cache.lookup_l2("test query")
        assert found is None

    def test_l2_fingerprint_mismatch_removes_entry(self):
        """L2 指纹不匹配时应从存储中移除。"""
        cache = CacheManager(max_size=10)
        cache.update_fingerprint("fp_v1")
        cache.store_l2("test query", _make_result("test"),
                       knowledge_type="general_knowledge")

        cache.update_fingerprint("fp_v2")
        cache.lookup_l2("test query")

        assert cache.l2_size == 0

    def test_l2_fingerprint_mismatch_increments_counter(self):
        """L2 指纹不匹配时 l2_fingerprint_mismatches 计数器应递增。"""
        cache = CacheManager(max_size=10)
        cache.update_fingerprint("fp_v1")
        cache.store_l2("test query", _make_result("test"),
                       knowledge_type="general_knowledge")

        cache.update_fingerprint("fp_v2")
        cache.lookup_l2("test query")

        stats = cache.get_stats()
        assert stats["l2_fingerprint_mismatches"] == 1
        assert stats["l2_misses"] == 1

    def test_l2_no_fingerprint_set_all_hits_pass(self):
        """L2 未设置指纹时（向后兼容），所有查找正常通过。"""
        cache = CacheManager(max_size=10)
        cache.store_l2("test query", _make_result("test"),
                       knowledge_type="general_knowledge")

        found = cache.lookup_l2("test query")
        assert found is not None

    def test_l1_l2_independent_fingerprint_validation(self):
        """L1 和 L2 的指纹校验应独立工作。"""
        cache = CacheManager(max_size=10)
        cache.update_fingerprint("fp_v1")
        cache.store("sess", "hash", _make_result("l1_v1"))
        cache.store_l2("test query", _make_result("l2_v1"),
                       knowledge_type="general_knowledge")

        cache.update_fingerprint("fp_v2")

        # 两者都应因指纹不匹配而 miss
        assert cache.lookup("sess", "hash") is None
        assert cache.lookup_l2("test query") is None
        assert cache.size == 0
        assert cache.l2_size == 0


class TestFingerprintSweep:
    """验证 _sweep_expired 在指纹不匹配时的行为。"""

    def test_sweep_removes_fingerprint_mismatched_l1(self):
        """_sweep_expired 应移除指纹不匹配的 L1 条目。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)
        cache.update_fingerprint("fp_v1")
        cache.store("sess", "hash_a", _make_result("a"))
        cache.store("sess", "hash_b", _make_result("b"))

        cache.update_fingerprint("fp_v2")

        removed = cache._sweep_expired(cache._store, "l1")
        assert removed == 2
        assert cache.size == 0

    def test_sweep_removes_fingerprint_mismatched_l2(self):
        """_sweep_expired 应移除指纹不匹配的 L2 条目。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)
        cache.update_fingerprint("fp_v1")
        cache.store_l2("query a", _make_result("a"))
        cache.store_l2("query b", _make_result("b"))

        cache.update_fingerprint("fp_v2")

        removed = cache._sweep_expired(cache._l2_store, "l2")
        assert removed == 2
        assert cache.l2_size == 0

    def test_sweep_keeps_fingerprint_matched_entries(self):
        """指纹匹配的条目不应被 _sweep_expired 移除。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)
        cache.update_fingerprint("fp_v1")
        cache.store("sess", "hash", _make_result("test"))

        # 不改变指纹，sweep 不应移除任何条目
        removed = cache._sweep_expired(cache._store, "l1")
        assert removed == 0
        assert cache.size == 1


class TestFingerprintStats:
    """验证指纹相关统计字段。"""

    def test_fingerprint_mismatches_in_get_stats_keys(self):
        """get_stats() 应包含 fingerprint_mismatches 和 l2_fingerprint_mismatches。"""
        cache = CacheManager(max_size=10)
        stats = cache.get_stats()
        assert "fingerprint_mismatches" in stats
        assert "l2_fingerprint_mismatches" in stats

    def test_fingerprint_mismatches_initial_value_zero(self):
        """初始化时 fingerprint_mismatches 应为 0。"""
        cache = CacheManager(max_size=10)
        stats = cache.get_stats()
        assert stats["fingerprint_mismatches"] == 0
        assert stats["l2_fingerprint_mismatches"] == 0

    def test_fingerprint_property(self):
        """fingerprint 属性应返回当前指纹值。"""
        cache = CacheManager(max_size=10)
        assert cache.fingerprint is None

        cache.update_fingerprint("test_fp")
        assert cache.fingerprint == "test_fp"

        cache.update_fingerprint(None)
        assert cache.fingerprint is None
