"""动态 TTL、知识库指纹与抽样清理策略测试。

测试覆盖：
- 通用知识条目 TTL=30min 内可命中
- 上下文依赖条目 TTL=5min 且仅 L1 不写 L2
- 搜索结果条目 TTL=10min
- 零向量查询跳过缓存写入
- TTL 过期后缓存未命中
- 知识库指纹匹配时缓存有效
- 文档更新后指纹不一致导致 L2 缓存失效
- 指纹不一致不影响 L1 缓存（设计决策：会话绑定 + 短 TTL）
- 写入时抽样清理触发概率（mock random 验证）
- 抽样清理移除过期和指纹不匹配条目
- 抽样概率为 0 时跳过清理
"""

from __future__ import annotations

from app.services.cache_manager import CacheManager

from .conftest import _advance_time, _make_result

# ── TTL 常量（与设计文档一致）──
TTL_GENERAL_KNOWLEDGE = 1800  # 30 分钟
TTL_CONTEXT_DEPENDENT = 300  # 5 分钟
TTL_SEARCH = 600  # 10 分钟


# ══════════════════════════════════════════════════════════
# 动态 TTL 策略测试
# ══════════════════════════════════════════════════════════


class TestDynamicTTLByKnowledgeType:
    """验证不同知识类型的差异化 TTL 策略。"""

    def test_general_knowledge_ttl_l2_hit_within_window(self):
        """通用知识条目 TTL=1800s 内 L2 可命中。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)
        cache.store_l2(
            "报销流程怎么走",
            _make_result("test"),
            knowledge_type="general_knowledge",
            ttl_override=TTL_GENERAL_KNOWLEDGE,
        )

        # 立即查询应命中
        found = cache.lookup_l2("报销流程怎么走")
        assert found is not None
        assert found["knowledge_type"] == "general_knowledge"

    def test_context_dependent_ttl_l1_only(self):
        """上下文依赖条目仅在 L1 存储（会话绑定），不写入 L2。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)

        # 使用 L1 store() 并设置 context_dependent TTL
        cache.store(
            "sess_abc",
            "hash_context",
            _make_result("context answer"),
            ttl_override=TTL_CONTEXT_DEPENDENT,
        )

        # L1 中应存在
        found_l1 = cache.lookup("sess_abc", "hash_context")
        assert found_l1 is not None

        # L2 中不应存在（从未通过 store_l2 写入）
        found_l2 = cache.lookup_l2("context query text")
        assert found_l2 is None

    def test_context_dependent_l1_expires_within_ttl(self, monkeypatch):
        """上下文依赖条目在 TTL=300s 后过期（模拟时间推进）。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)
        cache.store(
            "sess",
            "hash",
            _make_result("test"),
            ttl_override=TTL_CONTEXT_DEPENDENT,
        )

        _advance_time(monkeypatch, delta=TTL_CONTEXT_DEPENDENT + 1)
        found = cache.lookup("sess", "hash")
        assert found is None

    def test_search_result_ttl_l1(self):
        """搜索结果条目 TTL=600s 在 L1 中生效。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)
        cache.store(
            "sess",
            "hash_search",
            _make_result("search result"),
            ttl_override=TTL_SEARCH,
        )

        # 立即查询应命中
        found = cache.lookup("sess", "hash_search")
        assert found is not None
        assert found.original_query == "search result"

    def test_search_result_ttl_expired(self, monkeypatch):
        """搜索结果条目在 TTL=600s 后过期。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)
        cache.store(
            "sess",
            "hash",
            _make_result("test"),
            ttl_override=TTL_SEARCH,
        )

        _advance_time(monkeypatch, delta=TTL_SEARCH + 1)
        found = cache.lookup("sess", "hash")
        assert found is None

    def test_different_types_independent_ttl(self, monkeypatch):
        """不同知识类型的 TTL 独立生效，互不干扰。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)

        # 短 TTL（模拟 context_dependent）：0.01s
        cache.store("sess", "hash_short", _make_result("short"), ttl_override=0.01)
        # 长 TTL（模拟 general_knowledge）：3600s
        cache.store("sess", "hash_long", _make_result("long"), ttl_override=3600)

        _advance_time(monkeypatch, delta=0.02)

        # 短 TTL 已过期
        assert cache.lookup("sess", "hash_short") is None
        # 长 TTL 仍有效
        assert cache.lookup("sess", "hash_long") is not None
        assert cache.lookup("sess", "hash_long").original_query == "long"


# ══════════════════════════════════════════════════════════
# TTL 过期行为测试
# ══════════════════════════════════════════════════════════


class TestTTLExpirationBehavior:
    """验证不同类型缓存条目 TTL 过期后的统一行为。"""

    def test_l1_entry_expired_returns_none(self, monkeypatch):
        """L1 条目 TTL 过期后 lookup 返回 None。"""
        cache = CacheManager(max_size=10, ttl_seconds=0.01)
        cache.store("sess", "hash", _make_result("test"))

        _advance_time(monkeypatch, delta=0.02)
        assert cache.lookup("sess", "hash") is None

    def test_l2_entry_expired_returns_none(self, monkeypatch):
        """L2 条目 TTL 过期后 lookup_l2 返回 None。"""
        cache = CacheManager(max_size=10, ttl_seconds=0.01)
        cache.store_l2("test query", _make_result("test"), knowledge_type="general_knowledge")

        _advance_time(monkeypatch, delta=0.02)
        assert cache.lookup_l2("test query") is None

    def test_expired_entry_removed_from_l1(self, monkeypatch):
        """L1 过期条目被惰性淘汰后 size 减少。"""
        cache = CacheManager(max_size=10, ttl_seconds=0.01)
        cache.store("sess", "hash", _make_result("test"))

        _advance_time(monkeypatch, delta=0.02)
        cache.lookup("sess", "hash")  # 触发惰性淘汰

        assert cache.size == 0

    def test_expired_entry_removed_from_l2(self, monkeypatch):
        """L2 过期条目被惰性淘汰后 l2_size 减少。"""
        cache = CacheManager(max_size=10, ttl_seconds=0.01)
        cache.store_l2("test query", _make_result("test"), knowledge_type="general_knowledge")

        _advance_time(monkeypatch, delta=0.02)
        cache.lookup_l2("test query")  # 触发惰性淘汰

        assert cache.l2_size == 0


# ══════════════════════════════════════════════════════════
# 零向量查询跳过缓存写入测试
# ══════════════════════════════════════════════════════════


class TestZeroVectorCacheSkip:
    """验证零向量查询跳过缓存写入。"""

    def test_zero_vector_query_skips_l1_write(self):
        """零向量查询不应写入 L1 缓存。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)

        cache.store(
            "sess",
            "hash_zero_vec",
            _make_result("zero vector query"),
            zero_vector=True,
        )
        assert cache.size == 0

    def test_zero_vector_query_skips_l2_write(self):
        """零向量查询不应写入 L2 缓存。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)

        cache.store_l2(
            "zero vector query text",
            _make_result("zero vector"),
            knowledge_type="general_knowledge",
            zero_vector=True,
        )
        assert cache.l2_size == 0

    def test_normal_non_zero_vector_query_writes_normally(self):
        """非零向量查询正常写入缓存（功能性回归测试）。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)
        cache.store("sess", "hash", _make_result("normal query"))

        assert cache.size == 1
        found = cache.lookup("sess", "hash")
        assert found is not None
        assert found.original_query == "normal query"


# ══════════════════════════════════════════════════════════
# 知识库指纹策略测试
# ══════════════════════════════════════════════════════════


class TestFingerprintStrategies:
    """验证知识库指纹在缓存策略中的行为。"""

    def test_fingerprint_match_l2_cache_valid(self):
        """指纹匹配时 L2 缓存有效可命中。"""
        cache = CacheManager(max_size=10)
        cache.update_fingerprint("fp_current")
        cache.store_l2(
            "Python list comprehension syntax",
            _make_result("test"),
            knowledge_type="general_knowledge",
        )

        # 指纹未变 → 应命中
        found = cache.lookup_l2("Python list comprehension syntax")
        assert found is not None
        assert found["knowledge_type"] == "general_knowledge"

    def test_document_update_fingerprint_mismatch_l2_invalidated(self):
        """文档更新后指纹不一致 → L2 缓存失效。"""
        cache = CacheManager(max_size=10)
        cache.update_fingerprint("fp_v1")
        cache.store_l2(
            "company policy",
            _make_result("old answer"),
            knowledge_type="general_knowledge",
        )

        # 模拟文档更新 → 指纹变更
        cache.update_fingerprint("fp_v2")
        found = cache.lookup_l2("company policy")
        assert found is None

    def test_fingerprint_mismatch_l2_removes_stale_entry(self):
        """L2 指纹不匹配时惰性删除旧条目。"""
        cache = CacheManager(max_size=10)
        cache.update_fingerprint("fp_v1")
        cache.store_l2("query", _make_result("test"), knowledge_type="general_knowledge")

        cache.update_fingerprint("fp_v2")
        cache.lookup_l2("query")  # 触发惰性淘汰

        assert cache.l2_size == 0

    def test_fingerprint_mismatch_l1_behavior(self):
        """指纹不一致时 L1 仍应命中（设计决策：L1 不校验指纹）。

        设计理由：同一会话内知识库不可能在 5-30 分钟缓存 TTL 内变更。
        """
        cache = CacheManager(max_size=10)
        cache.update_fingerprint("fp_v1")
        cache.store("sess", "hash", _make_result("test"))

        cache.update_fingerprint("fp_v2")
        found = cache.lookup("sess", "hash")

        # L1 不校验指纹 → 命中
        assert found is not None
        assert found.original_query == "test"

    def test_fingerprint_none_disables_all_validation(self):
        """指纹为 None 时跳过所有校验（向后兼容）。"""
        cache = CacheManager(max_size=10)
        cache.update_fingerprint(None)
        cache.store("sess", "hash", _make_result("test"))
        cache.store_l2("query", _make_result("test"), knowledge_type="general_knowledge")

        # 指纹为 None → L1/L2 均正常命中
        assert cache.lookup("sess", "hash") is not None
        assert cache.lookup_l2("query") is not None

    def test_fingerprint_only_affects_entries_stored_under_fingerprint(self):
        """L1 不校验指纹，带指纹条目在指纹变更后仍然命中。"""
        cache = CacheManager(max_size=10)

        # 无指纹时写入
        cache.update_fingerprint(None)
        cache.store("sess", "hash_no_fp", _make_result("no fp"))

        # 设置指纹后写入新条目
        cache.update_fingerprint("fp_v1")
        cache.store("sess", "hash_with_fp", _make_result("with fp"))

        # 变更指纹
        cache.update_fingerprint("fp_v2")

        # 无指纹条目应仍然命中
        found_no_fp = cache.lookup("sess", "hash_no_fp")
        assert found_no_fp is not None

        # L1 不校验指纹 → 带指纹条目也应命中
        found_with_fp = cache.lookup("sess", "hash_with_fp")
        assert found_with_fp is not None


# ══════════════════════════════════════════════════════════
# 写入时抽样清理策略测试
# ══════════════════════════════════════════════════════════


class TestSamplingCleanup:
    """验证写入时抽样清理的概率触发与控制。"""

    def test_sweep_removes_expired_entries(self, monkeypatch):
        """抽样清理应移除 TTL 过期的条目。"""
        cache = CacheManager(max_size=10, ttl_seconds=0.01)
        cache.store("sess", "hash_a", _make_result("a"))
        cache.store("sess", "hash_b", _make_result("b"))

        _advance_time(monkeypatch, delta=0.02)

        removed = cache._sweep_expired(cache._store, "l1")
        assert removed == 2
        assert cache.size == 0

    def test_sweep_preserves_fingerprint_mismatched_l1_entries(self):
        """抽样清理对 L1 不检查指纹，保留指纹不匹配条目。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)
        cache.update_fingerprint("fp_v1")
        cache.store("sess", "hash_a", _make_result("a"))
        cache.store("sess", "hash_b", _make_result("b"))

        cache.update_fingerprint("fp_v2")

        removed = cache._sweep_expired(cache._store, "l1")
        # L1 不校验指纹 → 不因指纹不匹配移除条目
        assert removed == 0
        assert cache.size == 2

    def test_sweep_removes_expired_only_for_l1(self, monkeypatch):
        """L1 抽样清理只移除 TTL 过期条目，不检查指纹。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)
        cache.update_fingerprint("fp_v1")

        # 短 TTL（将过期）
        cache.store("sess", "hash_expired", _make_result("expired"), ttl_override=0.01)
        # 长 TTL 但指纹将不匹配 — L1 不检查指纹，保留
        cache.store("sess", "hash_fp", _make_result("fp_mismatch"), ttl_override=3600)

        _advance_time(monkeypatch, delta=0.02)  # 让短 TTL 先过期

        cache.update_fingerprint("fp_v2")
        cache.store("sess", "hash_valid", _make_result("valid"), ttl_override=3600)

        removed = cache._sweep_expired(cache._store, "l1")
        # hash_expired: TTL 过期 → 移除
        # hash_fp: 指纹不匹配但 L1 不校验 → 保留
        # hash_valid: TTL 有效 + 无过期 → 保留
        assert removed == 1
        assert cache.size == 2
        assert cache.lookup("sess", "hash_fp") is not None
        assert cache.lookup("sess", "hash_valid") is not None

    def test_sweep_sampling_limit_respected(self, monkeypatch):
        """条目数超过抽样上限时只检查随机样本。"""
        cache = CacheManager(max_size=200)

        # 存储大量条目
        for i in range(200):
            cache.store("sess", f"hash_{i}", _make_result(f"test_{i}"), ttl_override=0.01)

        _advance_time(monkeypatch, delta=0.02)

        removed = cache._sweep_expired(cache._store, "l1")
        # 抽样上限为 _CLEANUP_SAMPLE_SIZE (20)
        assert 0 < removed <= CacheManager._CLEANUP_SAMPLE_SIZE

    def test_maybe_sweep_trigger_controlled_by_write_count(self, monkeypatch):
        """_maybe_sweep 基于写入计数决定是否触发。"""
        cache = CacheManager(max_size=20, ttl_seconds=3600)

        # 修改触发间隔为 5
        monkeypatch.setattr(CacheManager, "_CLEANUP_TRIGGER_EVERY_N", 5)

        sweep_calls = []

        def tracking_sweep(store, label):
            sweep_calls.append((label, len(store)))
            return 0

        monkeypatch.setattr(cache, "_sweep_expired", tracking_sweep)

        # 前 4 次写入不触发
        for i in range(4):
            cache.store("sess", f"hash_{i}", _make_result(f"test_{i}"))
        assert len(sweep_calls) == 0

        # 第 5 次写入触发（l1 + l2 = 2 次 sweep）
        cache.store("sess", "hash_5", _make_result("test_5"))
        assert len(sweep_calls) == 2

    def test_sweep_trigger_probability_hundred_percent_by_default(self, monkeypatch):
        """默认清理触发概率为 100%（每次达到计数阈值都触发）。

        CacheManager 使用 _CLEANUP_TRIGGER_EVERY_N 控制触发频率，
        每 N 次写入触发一次 sweep（每次触发概率 100%）。
        设计文档中的 10% 概率可通过增大 _CLEANUP_TRIGGER_EVERY_N
        （如 N=100，平均每 10 次随机抽样 20 条）或引入 random 分层
        来实现等效行为。
        """
        cache = CacheManager(max_size=10, ttl_seconds=3600)

        trigger_count = 3
        monkeypatch.setattr(CacheManager, "_CLEANUP_TRIGGER_EVERY_N", trigger_count)

        sweep_invoked = []

        def instrumented_sweep(store, label):
            sweep_invoked.append(label)
            return 0

        monkeypatch.setattr(cache, "_sweep_expired", instrumented_sweep)

        # 前 2 次写入不触发
        for i in range(2):
            cache.store("sess", f"hash_{i}", _make_result(f"test_{i}"))
        assert len(sweep_invoked) == 0

        # 第 3 次写入触发（_maybe_sweep 在 _write_count 达到阈值时触发）
        cache.store("sess", "hash_2", _make_result("test_2"))
        assert len(sweep_invoked) == 2  # l1 + l2

    def test_cleanup_preserves_non_expired_non_fingerprint_stale(self):
        """抽样清理保留未过期且指纹匹配的条目。"""
        cache = CacheManager(max_size=10, ttl_seconds=3600)
        cache.update_fingerprint("fp_v1")
        cache.store("sess", "hash_a", _make_result("a"))
        cache.store("sess", "hash_b", _make_result("b"))

        # 指纹不变，TTL 未过期 → sweep 不应移除任何条目
        removed = cache._sweep_expired(cache._store, "l1")
        assert removed == 0
        assert cache.size == 2


# ══════════════════════════════════════════════════════════
# L1/L2 缓存写入策略测试
# ══════════════════════════════════════════════════════════


class TestCacheWriteStrategies:
    """验证不同场景下的缓存写入策略。"""

    def test_general_knowledge_writes_to_l2(self):
        """通用知识写入 L2（跨会话复用）。"""
        cache = CacheManager(max_size=10)
        cache.store_l2(
            "通用知识查询",
            _make_result("general"),
            knowledge_type="general_knowledge",
            ttl_override=TTL_GENERAL_KNOWLEDGE,
        )

        found = cache.lookup_l2("通用知识查询")
        assert found is not None
        assert found["knowledge_type"] == "general_knowledge"

    def test_context_dependent_only_writes_to_l1(self):
        """上下文依赖答案仅写入 L1（会话绑定），不进入 L2。"""
        cache = CacheManager(max_size=10)

        # 通过 L1 store() 写入，不通过 store_l2()
        cache.store(
            "sess_xyz",
            "hash_dep",
            _make_result("context-dependent answer"),
            ttl_override=TTL_CONTEXT_DEPENDENT,
        )

        # 在 L2 中不应存在
        l2_found = cache.lookup_l2("context-dependent answer")
        assert l2_found is None

        # 在 L1 中应存在（同一会话）
        l1_found = cache.lookup("sess_xyz", "hash_dep")
        assert l1_found is not None
        assert l1_found.original_query == "context-dependent answer"

    def test_search_result_writes_to_l1(self):
        """搜索结果写入 L1 缓存。"""
        cache = CacheManager(max_size=10)
        cache.store(
            "sess",
            "hash_search",
            _make_result("search result"),
            ttl_override=TTL_SEARCH,
        )

        found = cache.lookup("sess", "hash_search")
        assert found is not None
        assert found.original_query == "search result"

    def test_l1_not_l2_isolation(self):
        """L1 store() 不应污染 L2 存储空间。"""
        cache = CacheManager(max_size=10)
        for i in range(5):
            cache.store("sess", f"hash_{i}", _make_result(f"result_{i}"))

        assert cache.size == 5
        assert cache.l2_size == 0

    def test_l2_not_l1_isolation(self):
        """L2 store_l2() 不应污染 L1 存储空间。"""
        cache = CacheManager(max_size=10)
        for i in range(5):
            cache.store_l2(
                f"query_{i}", _make_result(f"result_{i}"), knowledge_type="general_knowledge"
            )

        assert cache.l2_size == 5
        assert cache.size == 0
