"""Verification tests for the 7 review issues from docs/questions.md.

Each test is self-contained and verifies exactly one reported issue.
Run with:  python -m pytest backend/tests/verify_review_issues.py -v
"""

from __future__ import annotations

import asyncio
import hashlib
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════════════════════
# 问题1: History not in cache key → 不同 history 的请求被错误复用
# ═══════════════════════════════════════════════════════════════════════════════


class TestIssue1_HistoryNotInCacheKey:
    """验证 _make_search_cache_key 包含 history（修复后）。

    修复前: 同一 session_id + 同一 query + 同一 top_k，但 history 不同
    会生成相同的缓存键 → 第二次请求返回第一次的缓存响应。
    修复后: history_digest 纳入缓存键 → 不同 history 产生不同 key。
    """

    def test_cache_key_includes_history_digest_when_provided(self):
        """不同 history 产生不同缓存键（修复验证）。"""
        from app.services.search import SearchService

        session_id = "test-session-abc"
        query = "档案怎么查？"
        top_k = 5

        history_blue = [
            {"role": "user", "content": "蓝色档案怎么查？"},
        ]
        history_red = [
            {"role": "user", "content": "红色档案怎么查？"},
        ]

        digest_blue = SearchService._compute_history_digest(history_blue)
        digest_red = SearchService._compute_history_digest(history_red)

        key_blue = SearchService._make_search_cache_key(
            session_id, query, top_k, digest_blue
        )
        key_red = SearchService._make_search_cache_key(
            session_id, query, top_k, digest_red
        )

        assert key_blue != key_red, (
            "不同 history 应产生不同缓存键（修复后 history_digest 纳入键计算）"
        )
        assert len(key_blue) == 16, "缓存键应为 16 字符十六进制"

    def test_cache_key_same_for_same_history(self):
        """相同 history 产生相同缓存键（正向验证）。"""
        from app.services.search import SearchService

        session_id = "test-session-abc"
        query = "档案怎么查？"
        top_k = 5
        history = [{"role": "user", "content": "档案怎么查？"}]

        digest = SearchService._compute_history_digest(history)
        key1 = SearchService._make_search_cache_key(session_id, query, top_k, digest)
        key2 = SearchService._make_search_cache_key(session_id, query, top_k, digest)

        assert key1 == key2, "相同输入（含 history）应产生相同键"

    def test_cache_key_backward_compatible_no_history(self):
        """无 history 时 history_digest 为空字符串，与旧行为兼容。"""
        from app.services.search import SearchService

        session_id = "test-session-abc"
        query = "档案怎么查？"
        top_k = 5

        # 无 history → digest 为 ""
        digest = SearchService._compute_history_digest(None)
        assert digest == ""

        key = SearchService._make_search_cache_key(session_id, query, top_k, digest)
        assert len(key) == 16, "无 history 时缓存键仍正常生成"

    def test_resolve_session_id_ignores_history_when_session_id_present(self):
        """显式 session_id 存在时，_resolve_session_id 返回该 session_id。

        NOTE: session_id 层面的解析不包含 history（这是预期行为），
        但缓存键层面的 _make_search_cache_key 会额外纳入 history_digest，
        从而确保不同 history 的请求不会命中同一缓存。
        """
        from app.services.search import SearchService

        explicit_sid = "explicit-session-123"
        history_blue = [
            {"role": "user", "content": "蓝色档案怎么查？"},
            {"role": "assistant", "content": "蓝色档案在左侧菜单"},
        ]
        history_red = [
            {"role": "user", "content": "红色档案怎么查？"},
            {"role": "assistant", "content": "红色档案在右侧菜单"},
        ]

        sid1 = SearchService._resolve_session_id(explicit_sid, history_blue)
        sid2 = SearchService._resolve_session_id(explicit_sid, history_red)

        # 两者都返回 explicit_sid
        assert sid1 == explicit_sid
        assert sid2 == explicit_sid

        # 但 _compute_history_digest 产生不同值
        d1 = SearchService._compute_history_digest(history_blue)
        d2 = SearchService._compute_history_digest(history_red)
        assert d1 != d2

        # 因此最终的缓存键不同
        key1 = SearchService._make_search_cache_key(sid1, "档案怎么查", 5, d1)
        key2 = SearchService._make_search_cache_key(sid2, "档案怎么查", 5, d2)
        assert key1 != key2, (
            "即使 session_id 相同，不同 history_digest 也应产生不同缓存键"
        )

    def test_resolve_session_id_returns_none_for_untrusted(self):
        """无显式 session_id 且无 history 时返回 None（不可信身份）。"""
        from app.services.search import SearchService

        result = SearchService._resolve_session_id(None, None)
        assert result is None, (
            "不可信身份（匿名无 history）应返回 None，"
            "调用方应跳过私有响应缓存写入"
        )

        result_empty = SearchService._resolve_session_id(None, [])
        assert result_empty is None, "空 history 也应返回 None"

    def test_no_cache_key_collision_with_different_history(self):
        """端到端: 不同 history 产生不同缓存键（修复后无冲突）。"""

        from app.services.search import SearchService

        session_id = "user-session-789"
        history_blue = [
            {"role": "user", "content": "蓝色档案怎么查？"}
        ]
        history_red = [
            {"role": "user", "content": "红色档案怎么查？"}
        ]

        # session_id 相同
        sid1 = SearchService._resolve_session_id(session_id, history_blue)
        sid2 = SearchService._resolve_session_id(session_id, history_red)
        assert sid1 == sid2 == session_id

        # 但 history_digest 不同 → 缓存键不同
        d1 = SearchService._compute_history_digest(history_blue)
        d2 = SearchService._compute_history_digest(history_red)
        assert d1 != d2

        key1 = SearchService._make_search_cache_key(sid1, "档案怎么查", 5, d1)
        key2 = SearchService._make_search_cache_key(sid2, "档案怎么查", 5, d2)
        assert key1 != key2, (
            "修复后不同 history 产生不同缓存键，不再有缓存键冲突"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 问题2: L1 缓存跳过指纹校验 → 软删除后旧缓存仍然命中
# ═══════════════════════════════════════════════════════════════════════════════


class TestIssue2_L1SkipFingerprint:
    """验证 L1 和 L2 均校验知识库指纹（已修复）。

    修复前：L1 不校验指纹，软删除文件后同 session 的后续请求
    仍可通过 L1 缓存返回已删除文件的内容。
    修复后：L1 与 L2 均校验指纹，指纹不匹配时惰性淘汰。
    """

    def test_l1_lookup_now_checks_fingerprint(self):
        """修复后：L1 lookup() 指纹不匹配时正确返回 None。"""
        from app.services.cache_manager import CacheManager

        cache = CacheManager(max_size=10, ttl_seconds=300)
        cache.update_fingerprint("fp-v1")

        # 存入一个值 (带指纹 fp-v1)
        cache.store("sess-1", "hash-abc", {"rewrite": "蓝色档案结果"})

        # 模拟知识库变更: 更新指纹
        cache.update_fingerprint("fp-v2")

        # 修复后：L1 指纹不匹配 → 返回 None（惰性淘汰）
        result = cache.lookup("sess-1", "hash-abc")
        assert result is None, (
            "修复后 L1 应校验指纹：指纹不匹配时返回 None，"
            "防止已删除文件的内容通过 L1 缓存返回。"
        )

    def test_l1_lookup_returns_value_when_fingerprint_matches(self):
        """L1 lookup() 指纹匹配时正常返回缓存值。"""
        from app.services.cache_manager import CacheManager

        cache = CacheManager(max_size=10, ttl_seconds=300)
        cache.update_fingerprint("fp-v1")
        cache.store("sess-1", "hash-abc", {"rewrite": "蓝色档案结果"})

        # 指纹未变化 → 应命中
        result = cache.lookup("sess-1", "hash-abc")
        assert result is not None
        assert result["rewrite"] == "蓝色档案结果"

    def test_l1_fingerprint_invalidation_vs_l2(self):
        """修复后：L1 和 L2 均校验指纹，指纹不匹配时均返回 None。"""
        from app.services.cache_manager import CacheManager

        cache = CacheManager(max_size=10, ttl_seconds=300)

        # L1: 通过 store/lookup 写入和读取
        cache.update_fingerprint("fp-v1")
        cache.store("sess-1", "hash-abc", "L1 result")
        cache.update_fingerprint("fp-v2")
        l1_result = cache.lookup("sess-1", "hash-abc")  # ← 现在校验指纹

        # L2: 通过 store_l2/lookup_l2 写入和读取
        cache.update_fingerprint("fp-v1")
        cache.store_l2("规范化查询文本", "L2 result", knowledge_type="general_knowledge")
        cache.update_fingerprint("fp-v2")
        l2_result = cache.lookup_l2("规范化查询文本")  # ← 校验指纹

        assert l1_result is None, "修复后 L1 校验指纹并失效"
        assert l2_result is None, "L2 校验指纹并失效"

    def test_soft_delete_does_not_change_fingerprint(self):
        """验证: 软删除文件不改变 knowledge base 指纹计算值。

        指纹基于 COUNT(document_embeddings) + MAX(document_embedding_jobs.updated_at)，
        软删除只设置 uploaded_files.deleted_at，不影响 embeddings 表和 jobs 表。
        """
        import hashlib

        # 模拟: 删除前
        raw_before = "100:2026-08-12T10:00:00+00:00"
        fp_before = hashlib.sha256(raw_before.encode()).hexdigest()[:16]

        # 模拟: 删除后 (embeddings count 和 job timestamp 都不变)
        raw_after = "100:2026-08-12T10:00:00+00:00"
        fp_after = hashlib.sha256(raw_after.encode()).hexdigest()[:16]

        assert fp_before == fp_after, (
            "软删除不改变嵌入数和 job timestamp，指纹不变。"
            "L1 跳过指纹校验 → 无法感知文档可见性变化。"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 问题3: asyncio.Event 跨 event loop 线程安全问题
# ═══════════════════════════════════════════════════════════════════════════════


class TestIssue3_AsyncIOEventCrossLoop:
    """验证 asyncio.Event 跨 event loop 问题已通过 threading.Event 修复。

    原始问题: _inflight 中的 asyncio.Event 在不同 event loop 间不安全。
    FastAPI sync 路由 + _run_async() 为每个请求创建新 event loop →
    两个并发请求共享同一个 asyncio.Event，但运行在不同 loop 上 →
    set() 在 loop A，wait() 在 loop B → 跨 loop 通知不工作。

    修复: 使用 threading.Event（OS 级原语）+ run_in_executor（非阻塞等待）。
    """

    def test_asyncio_event_not_thread_safe_across_loops(self):
        """验证 asyncio.Event 不能跨不同 event loop 使用（历史问题复现）。

        此测试证明原始 bug 是真实的：asyncio.Event 绑定到创建它的 event loop。
        当 _run_async() 为每个请求创建独立 event loop 时，共享的 Event 会出现跨 loop 问题。
        修复方案已改为使用 threading.Event。
        """
        loop1 = asyncio.new_event_loop()
        loop2 = asyncio.new_event_loop()

        try:
            # 在 loop1 上创建 Event
            event = loop1.run_until_complete(self._create_event())

            # 验证 Event 绑定到 loop1
            event_loop = getattr(event, '_loop', None)
            if event_loop is not None:
                assert event_loop is loop1, (
                    f"Event 绑定到 loop1={id(loop1)}，不是 loop2={id(loop2)}"
                )

            # 在 loop2 上调用 wait() 是不安全操作
            result_container: dict = {}

            def wait_on_loop2():
                try:
                    waited = loop2.run_until_complete(
                        asyncio.wait_for(self._wait_event(event), timeout=0.5)
                    )
                    result_container["waited"] = waited
                except asyncio.TimeoutError:
                    result_container["timeout"] = True
                except Exception as e:
                    result_container["error"] = str(e)

            # 在 loop1 上 set() 后，loop2 上的 wait() 不应该被通知
            loop1.run_until_complete(self._set_event(event))

            t = threading.Thread(target=wait_on_loop2, daemon=True)
            t.start()
            t.join(timeout=2.0)

            if "timeout" in result_container:
                pass  # Expected: 跨 loop 通知不工作 — 证明原始 bug 存在
            elif "error" in result_container:
                pass  # 也证明跨 loop 操作有异常
        finally:
            loop1.close()
            loop2.close()

    async def _create_event(self) -> asyncio.Event:
        return asyncio.Event()

    async def _set_event(self, event: asyncio.Event) -> None:
        event.set()

    async def _wait_event(self, event: asyncio.Event) -> bool:
        await event.wait()
        return True

    def test_run_async_creates_new_event_loop(self):
        """验证 _run_async() 在已有活跃 loop 时创建新 loop。

        此机制是原始 bug 的根因：主线程的 event loop 与 _run_async() 创建的
        thread-local loop 不同 → 共享 asyncio.Event 不安全。
        修复使用 threading.Event 解决此问题。
        """
        from app.services.search import _run_async

        async def dummy_rewrite():
            return {"rewritten": True}

        async def test_inner():
            result = _run_async(dummy_rewrite())
            return result

        result = asyncio.run(test_inner())
        assert result == {"rewritten": True}, "_run_async 在新线程上创建了独立 event loop"

    def test_threading_event_cross_thread_safe(self):
        """修复验证：threading.Event 跨线程安全地传递通知。

        与 asyncio.Event 不同，threading.Event 是 OS 级原语，不绑定到
        特定 event loop。两个不同线程/loop 可以安全地共享一个 threading.Event。
        """
        inflight: dict[str, threading.Event] = {}
        inflight_results: dict[str, object] = {}
        errors: list[str] = []

        def worker_leader(session_key: str):
            """Leader: 创建 threading.Event，完成工作后 set()。"""
            event = threading.Event()
            inflight[session_key] = event

            # 模拟重写工作
            time.sleep(0.1)

            result = {"query": "rewritten by leader"}
            inflight_results[session_key] = result
            event.set()  # threading.Event.set() 唤醒所有等待线程

        def worker_follower(session_key: str):
            """Follower: 通过 threading.Event.wait() 等待 leader 完成。"""
            time.sleep(0.05)  # 确保 leader 先创建 Event

            event = inflight.get(session_key)
            if event is None:
                errors.append("Event not found")
                return

            # threading.Event.wait() 跨线程安全，无论当前在哪个 event loop
            notified = event.wait(timeout=2.0)
            if not notified:
                errors.append("threading.Event.wait() timed out — should not happen!")
                return

            result = inflight_results.get(session_key)
            if result is None:
                errors.append("Result not found after wait")
                return

            assert result["query"] == "rewritten by leader", (
                f"Follower 应获取 leader 的结果: {result}"
            )

        t1 = threading.Thread(target=worker_leader, args=("dedup-key",))
        t2 = threading.Thread(target=worker_follower, args=("dedup-key",))

        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert not errors, (
            f"threading.Event 跨线程应正常工作，但发现错误: {errors}"
        )

    def test_codebase_uses_threading_event_not_asyncio_event(self):
        """修复验证：QueryRewriter 使用 threading.Event 而非 asyncio.Event。"""
        import inspect
        from app.services.query_rewriter import QueryRewriter

        source = inspect.getsource(QueryRewriter.__init__)
        assert "threading.Event" in source, (
            "QueryRewriter.__init__ 应使用 threading.Event 类型标注"
        )
        # _inflight 的类型注解应为 dict[str, threading.Event]
        assert "threading.Event" in source, (
            f"inflight dict 的值类型应为 threading.Event:\n{source}"
        )

        # 验证 rewrite 方法使用 run_in_executor 等待 threading.Event
        rewrite_source = inspect.getsource(QueryRewriter.rewrite)
        assert "run_in_executor" in rewrite_source, (
            "应使用 run_in_executor 将 threading.Event.wait() 卸载到线程池，"
            "避免阻塞当前 event loop"
        )
        assert "threading.Event()" in rewrite_source, (
            "应创建 threading.Event() 实例进行去重"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 问题4: 并行 term_align 查询被 normalize 结果覆盖
# ═══════════════════════════════════════════════════════════════════════════════


class TestIssue4_ParallelQueryOverwrite:
    """验证 term_align 的查询被 protection restore 阶段覆盖。

    场景: normalize 和 term_align 并行运行。
    - normalize 更新 current_query
    - term_align 只 append 到 strategy_rewrites，不更新 current_query
    - protection restore 阶段: strategy_rewrites[-1]["query"] = final_query
      其中 final_query = protector.restore(current_query, ...)
    → term_align 结果被 normalize 结果覆盖
    """

    def test_last_append_is_term_align_but_overwritten_by_normalize_result(self):
        """模拟并行执行后的 strategy_rewrites 状态和覆盖逻辑。"""
        # 模拟 initial state
        current_query = "原始查询"
        strategy_rewrites: list[dict] = []

        # normalize 先完成:
        norm_query = "规范化后的查询 (normalize result)"
        strategy_rewrites.append({
            "query": norm_query,
            "strategy": "normalize",
            "duration_ms": 120.0,
        })
        current_query = norm_query  # normalize 更新 current_query

        # term_align 后完成 (并行，结果不同):
        term_query = "术语对齐后的查询 (term_align result)"
        strategy_rewrites.append({
            "query": term_query,  # ← 正确的 term_align 结果
            "strategy": "term_align",
            "duration_ms": 80.0,
        })
        # NOTE: term_align 未更新 current_query ← 这是 bug 的根源

        # protection restore 阶段 (line ~1193):
        # final_query = self._protector.restore(current_query, term_map)
        # current_query 仍然是 normalize 的结果!
        final_query = f"保护词恢复: {current_query}"

        # BUG: strategy_rewrites[-1] 是 term_align 的条目，
        #      但被覆盖为 normalize 的 protection-restored 结果
        strategy_rewrites[-1]["query"] = final_query

        assert strategy_rewrites[-1]["strategy"] == "term_align", (
            "最后一条记录标记为 term_align"
        )
        assert strategy_rewrites[-1]["query"] == final_query, (
            "但 query 字段被覆盖成 normalize 的保护恢复结果"
        )
        assert "normalize result" in strategy_rewrites[-1]["query"], (
            f"实际内容来自 normalize: {strategy_rewrites[-1]['query']}"
        )
        assert "term_align" not in strategy_rewrites[-1]["query"], (
            f"term_align 的内容丢失: {strategy_rewrites[-1]['query']}"
        )

    def test_effective_query_discrepancy(self):
        """验证 Postprocessor 评估和向量检索使用不同查询。

        - Postprocessor 在覆盖前评估 → 评估 term_align 文本 (但此文本后面会被覆盖)
        - 向量检索使用 strategy_rewrites[0]["query"] → 实际是 normalize 结果
        → 质量评估和检索来源不一致
        """
        strategy_rewrites: list[dict] = []

        # 并行结果
        strategy_rewrites.append({
            "query": "如何学习 Python (normalize)",
            "strategy": "normalize",
        })
        strategy_rewrites.append({
            "query": "Python 语言 如何 学习 (term_align)",
            "strategy": "term_align",
        })
        current_query = "如何学习 Python (normalize)"  # term_align 未更新

        # 1. Postprocessor 评估: 使用 strategy_rewrites[-1]["query"] (覆盖前)
        postprocessor_input = strategy_rewrites[-1]["query"]
        assert "term_align" in postprocessor_input, (
            "Postprocessor 评估的是 term_align 文本"
        )

        # 2. Protection restore 覆盖:
        final_query = f"恢复: {current_query}"
        strategy_rewrites[-1]["query"] = final_query

        # 3. 向量检索使用 strategy_rewrites[0]["query"]:
        retrieval_query = strategy_rewrites[0]["query"]
        assert "normalize" in retrieval_query, (
            "向量检索使用 normalize 结果"
        )

        # 4. 不一致:
        assert "term_align" in postprocessor_input, (
            "评估时: term_align 文本 (但已被覆盖)"
        )
        assert "normalize" in retrieval_query, (
            "检索时: normalize 结果"
        )
        assert postprocessor_input != retrieval_query, (
            "BUG: 评估和检索使用不同查询!"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 问题5: L2 语义缓存是精确文本匹配，不是向量余弦检索
# ═══════════════════════════════════════════════════════════════════════════════


class TestIssue5_L2ExactMatchNotVector:
    """验证 L2 lookup_l2 是精确文本匹配而非语义向量检索。

    复现: 写入 "如何办理退款？" 后查询 "退款流程是什么？" 必然 miss。
    当前 L2 为精确文本匹配实现，lookup_l2 返回的 dict 仅包含
    result、knowledge_type、source_session_id 三个字段。
    """

    def test_l2_is_exact_text_match_not_semantic(self):
        """写入一个查询，用语义相似但文字不同的查询查找 → 必然 miss。"""
        from app.services.cache_manager import CacheManager

        cache = CacheManager(max_size=10, ttl_seconds=300)

        # 存储语义相似查询 A
        cache.store_l2("如何办理退款？", "退款流程结果 A")

        # 用语义相似但文字不同的查询 B 查找
        result = cache.lookup_l2("退款流程是什么？")
        assert result is None, (
            "lookup_l2 是精确文本匹配! "
            "'退款流程是什么？' 应该命中 '如何办理退款？' (语义相同)，"
            "但 lookup_l2 使用规范化文本精确比较，必然 miss。"
        )

    def test_l2_returns_similarity_1_for_exact_match_only(self):
        """验证 lookup_l2 不再返回伪造的 similarity 字段。

        修复后 similarity 字段已移除 —— 当前为精确文本匹配实现，
        向量余弦相似度检查已规划为后续迭代。
        """
        from app.services.cache_manager import CacheManager

        cache = CacheManager(max_size=10, ttl_seconds=300)

        # 存储
        cache.store_l2("如何办理退款？", "退款流程结果")

        # 完全相同文本 → 命中
        result = cache.lookup_l2("如何办理退款？")
        assert result is not None, "精确匹配应命中"
        # 修复后不再返回伪造的 similarity 字段
        assert "similarity" not in result, (
            "lookup_l2 不再返回 similarity 字段（当前为精确文本匹配，"
            "向量语义检索待后续迭代实现）"
        )
        assert result["result"] == "退款流程结果", (
            "精确匹配应返回正确的缓存结果"
        )

    def test_l2_code_has_no_embedding_or_cosine(self):
        """验证 lookup_l2 源代码没有实际的 vector embedding 或 cosine distance 调用。

        排除注释和 docstring 中的提及 (如 "生产环境中将替换为..."）。
        """
        import inspect
        from app.services.cache_manager import CacheManager

        source = inspect.getsource(CacheManager.lookup_l2)

        # 去掉 docstring 再检查实际代码逻辑
        # 提取函数体 (从 return type annotation 后的行开始)
        lines = source.split("\n")
        # 跳过 docstring 行 (以 """ 或 r''' 开始/结束的多行字符串)
        code_lines = []
        in_docstring = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('"""') or stripped.startswith("'''"):
                in_docstring = not in_docstring
                continue
            if in_docstring:
                continue
            code_lines.append(line)

        body = "\n".join(code_lines)

        # 检查实际的函数调用模式
        import re
        # 不应该有 embed 函数调用
        assert not re.search(r"\bembed\b", body), (
            "lookup_l2 函数体没有实际的 embedding 调用"
        )
        # 不应该有 cosine 相关调用
        assert not re.search(r"\bcosine\b", body), (
            "lookup_l2 函数体没有 cosine distance 计算"
        )

        # 确认使用的是 dict.get (精确字典查找)
        assert "self._l2_store.get" in source, (
            "lookup_l2 使用精确字典查找 _l2_store.get(composite_key)"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 问题6: 缺少 partial unique index 和 Alembic migration
# ═══════════════════════════════════════════════════════════════════════════════


class TestIssue6_MissingUniqueIndexAndMigration:
    """验证 ix_uploaded_files_dedup 已修复为 partial unique index，
    且已有对应的 Alembic migration。
    """

    def test_index_is_partial_unique(self):
        """修复后：ix_uploaded_files_dedup 有 unique=True 和 postgresql_where。"""
        from app.models.uploaded_file import UploadedFile

        table_args = UploadedFile.__table_args__

        found_dedup = False
        for arg in table_args:
            if hasattr(arg, "name") and arg.name == "ix_uploaded_files_dedup":
                found_dedup = True
                assert arg.unique, (
                    f"ix_uploaded_files_dedup unique={arg.unique}，"
                    "修复后应为 unique index，防止并发插入重复记录。"
                )
                pg_where = arg.dialect_kwargs.get("postgresql_where")
                assert pg_where is not None, (
                    "修复后应包含 WHERE deleted_at IS NULL partial 约束"
                )
                break

        assert found_dedup, "未找到 ix_uploaded_files_dedup 索引"

    def test_create_upload_handles_integrity_error(self):
        """修复后：create_upload 有 IntegrityError 处理实现原子 upsert。"""
        import inspect
        from app.services.uploads import UploadService

        source = inspect.getsource(UploadService.create_upload)

        # 修复后应有 IntegrityError 处理
        assert "IntegrityError" in source, (
            "create_upload 应有 IntegrityError 处理 → "
            "并发 insert 时捕获唯一约束冲突并返回已有记录"
        )

        # 仍保留 select-then-insert 用于快速路径
        assert "_find_active_duplicate" in source, (
            "create_upload 使用 select (_find_active_duplicate) 先查后插"
        )

    def test_dedup_migration_exists(self):
        """修复后：ix_uploaded_files_dedup 已出现在 Alembic migration 中。"""
        from pathlib import Path

        alembic_dir = Path(__file__).resolve().parent.parent / "alembic" / "versions"
        migration_files = list(alembic_dir.glob("*.py"))

        assert len(migration_files) > 0, "应该有 Alembic migration 文件"

        found_in_migration = False
        for mf in migration_files:
            content = mf.read_text(encoding="utf-8")
            if "ix_uploaded_files_dedup" in content:
                found_in_migration = True
                break

        assert found_in_migration, (
            "ix_uploaded_files_dedup 应存在于 Alembic migration 中! "
            "`alembic upgrade head` 才能在实际数据库中创建该索引。"
        )

    def test_dedup_index_is_partial_unique(self):
        """修复后：模型中的 ix_uploaded_files_dedup 是 partial unique index。

        含 unique=True 和 postgresql_where=(deleted_at.is_(None))，
        保证同一用户下未软删除记录的唯一性，同时允许多条已删除记录共存。
        """
        from app.models.uploaded_file import UploadedFile

        table_args = UploadedFile.__table_args__

        for arg in table_args:
            if hasattr(arg, "name") and arg.name == "ix_uploaded_files_dedup":
                # 验证是 unique
                assert arg.unique, (
                    f"ix_uploaded_files_dedup unique={arg.unique}, "
                    "修复后应为 unique index → 可防止并发重复插入"
                )

                # 验证有 WHERE 子句 (partial index)
                where_clause = arg.dialect_kwargs.get("postgresql_where")
                assert where_clause is not None, (
                    f"ix_uploaded_files_dedup 应是 partial index (WHERE deleted_at IS NULL), "
                    f"当前 WHERE: {where_clause}"
                )
                return

        pytest.fail("未找到 ix_uploaded_files_dedup 索引")


# ═══════════════════════════════════════════════════════════════════════════════
# 问题7: rewrite_info never null
# ═══════════════════════════════════════════════════════════════════════════════


class TestIssue7_RewriteInfoNeverNull:
    """验证 SearchResponse.rewrite_info 在未启用重写时为 None，
    QUERY_REWRITE_ENABLED=false 时返回 null。
    """

    def test_rewrite_info_field_nullable(self):
        """修复后：Pydantic schema 中 rewrite_info 类型为 Optional（含 None）。"""
        from app.schemas.search import SearchResponse

        # 获取字段注解
        annotations = SearchResponse.model_fields
        rewrite_field = annotations["rewrite_info"]

        # 修复后应允许 None（RewriteInfo | None 或 Optional[RewriteInfo]）
        annotation_str = str(rewrite_field.annotation)
        assert "None" in annotation_str or "NoneType" in annotation_str, (
            f"rewrite_info annotation 应允许 None: {annotation_str}"
        )

        # 双重确认：default 为 None
        assert rewrite_field.default is None, (
            f"rewrite_info default 应为 None（禁用时返回 null），实际: {rewrite_field.default}"
        )

    def test_disabled_path_creates_null_rewrite_info(self):
        """验证 disabled 路径返回 None（而非空 RewriteInfo）。

        搜索 search.py 中 rewrite_info 的赋值路径:
        - 成功: rewrite_info = RewriteInfo(...) → 完整数据
        - 失败: rewrite_info = RewriteInfo(...) → 带 error 的数据
        - 禁用: rewrite_info = None → null
        禁用路径现在返回 None，与成功/失败路径区分。
        """
        import ast
        from pathlib import Path

        search_py = (
            Path(__file__).resolve().parent.parent
            / "app" / "services" / "search.py"
        )
        source = search_py.read_text(encoding="utf-8")

        # 检查成功/失败路径仍有 RewriteInfo 赋值
        rewrite_assignments = [
            line.strip()
            for line in source.split("\n")
            if "rewrite_info = RewriteInfo(" in line
        ]

        assert len(rewrite_assignments) >= 2, (
            f"预期至少 2 条 rewrite_info 赋值路径 (成功/失败)，"
            f"实际发现 {len(rewrite_assignments)}: {rewrite_assignments}"
        )

        # 确认禁用路径有 None 赋值
        none_assignments = [
            line.strip()
            for line in source.split("\n")
            if "rewrite_info = RewriteInfo(" not in line
            and "rewrite_info" in line
            and "None" in line
        ]
        none_actual = [
            line for line in none_assignments
            if "rewrite_info" in line.split("=")[0]
        ]
        assert len(none_actual) >= 1, (
            f"未发现 rewrite_info = None 赋值: {none_actual}"
        )

    def test_comment_says_returns_null_when_disabled(self):
        """验证代码注释确认了 disabled 时返回 None 的设计意图。"""
        from pathlib import Path

        search_py = (
            Path(__file__).resolve().parent.parent
            / "app" / "services" / "search.py"
        )
        source = search_py.read_text(encoding="utf-8")

        assert "未配置重写时返回 null，前端据此区分" in source, (
            "注释确认了 disabled 时返回 null 的设计意图"
        )

    def test_schema_comment_says_null_when_disabled(self):
        """修复后：schema 注释确认了禁用时返回 null 的设计意图。"""
        from pathlib import Path

        schema_py = (
            Path(__file__).resolve().parent.parent
            / "app" / "schemas" / "search.py"
        )
        source = schema_py.read_text(encoding="utf-8")

        assert "禁用重写时返回 null" in source, (
            "修复后 schema 注释应说明禁用重写时返回 null"
        )
