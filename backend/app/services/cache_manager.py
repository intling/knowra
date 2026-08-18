"""查询重写结果的内存 L1 精确缓存（绑定会话 ID）。

会话内缓存策略（模块一）：
    - 缓存 Key 绑定会话 ID：不同会话的相同问题不共享缓存
    - 精确匹配：仅当原始 Query 字符串逐字符完全一致时命中

跨会话 L2 精确缓存策略（模块二）：
    - 基于规范化文本的精确匹配（逐字符比较）
    - 仅通用知识允许跨会话复用
    - 需经过上下文相关性校验后返回
    - 注意：当前为精确文本匹配实现，向量语义检索（余弦相似度 > 0.95）已
      规划为后续迭代（见 OpenSpec query-rewriting-phase2）

知识库指纹校验：
    - 每条缓存条目存储写入时的知识库指纹
    - L1 和 L2 缓存读取时对比当前指纹与存储指纹：不匹配则视为过期（惰性淘汰）
    - 会话内可能发生文档上传/删除/替换操作，L1 指纹校验确保已删除文档的内容不会通过缓存返回
    - 指纹为 ``None`` 时跳过校验（兼容旧数据）

泛型设计：
    CacheManager 是类型无关的通用 LRU 缓存，可存储任意类型的值。
    默认用于 RewriteResult（查询重写结果），也可用于 SearchResponse（最终搜索响应）。

Usage::

    # 查询重写缓存
    cache = CacheManager(max_size=1000, ttl_seconds=3600.0)
    result = cache.lookup(session_id="sess_abc", query_hash="abc123...")

    # 搜索响应缓存
    response_cache = CacheManager(max_size=100, ttl_seconds=600.0)
    response = response_cache.lookup(session_id="sess_abc", query_hash="def456...")

    # 知识库指纹注入（搜索管线中使用）
    cache.update_fingerprint("a1b2c3d4e5f67890")
"""

from __future__ import annotations

import random
import time
from collections import OrderedDict
from typing import Any

from app.core.logging import get_logger


class CacheManager:
    """类型无关的内存精确匹配（L1）缓存（会话绑定） + L2 精确文本缓存 + 知识库指纹校验。

    基于 OrderedDict 实现 LRU 淘汰策略，每条缓存条目有独立的 TTL。
    适用于 FastAPI 单线程异步事件循环模型；如需并发访问，请在外部
    使用 ``asyncio.Lock``。

    会话绑定：
        缓存键 = hash(session_id + query_hash)，确保不同会话的
        相同查询不会错误共享缓存结果。

    知识库指纹：
        每条缓存条目在写入时携带当前知识库指纹，读取时校验。
        指纹不匹配 → 惰性淘汰（视为过期），无需手动清除。
        指纹为 ``None`` 时跳过校验（向后兼容、测试场景）。
        L1 和 L2 均执行指纹校验——会话内可能发生文档变更（上传/删除/替换）。

    泛型使用：
        存储和返回类型为 ``Any``，调用方负责类型转换。
        典型用例：缓存 RewriteResult、SearchResponse 等。
    """

    # ── 写入时抽样清理常量（Redis active-expiration 模式）──
    _CLEANUP_SAMPLE_SIZE: int = 20  # 每次抽样检查的条目数
    _CLEANUP_TRIGGER_EVERY_N: int = 10  # 每 N 次写入触发一次清理
    _STATS_LOG_INTERVAL: float = 300.0  # 统计快照输出间隔（秒）

    def __init__(
        self, *, max_size: int = 1000, ttl_seconds: float = 3600.0, max_l2_size: int = 500
    ) -> None:
        self._max_size = max_size
        self._max_l2_size = max_l2_size
        self._ttl = ttl_seconds
        # ── 当前知识库指纹（外部注入，惰性校验用）──
        # None → 指纹校验未启用 / 向后兼容
        self._fingerprint: str | None = None
        # L1 条目格式：(inserted_at_monotonic, entry_ttl_seconds, value, kb_fingerprint | None)
        self._store: OrderedDict[str, tuple[float, float, Any, str | None]] = OrderedDict()
        # L2 条目格式：
        # (inserted_at_monotonic, entry_ttl_seconds, value, knowledge_type,
        #  session_id, kb_fingerprint | None)
        self._l2_store: OrderedDict[str, tuple[float, float, Any, str, str | None, str | None]] = (
            OrderedDict()
        )
        self._logger = get_logger(__name__)

        # ── 统计计数器 ──
        self._stats: dict[str, int] = {
            "hits": 0,
            "misses": 0,
            "l2_hits": 0,
            "l2_misses": 0,
            "evictions": 0,
            "expirations": 0,
            "sweep_removed": 0,
            "fingerprint_mismatches": 0,
            "l2_fingerprint_mismatches": 0,
        }
        self._write_count: int = 0
        self._last_stats_log: float = time.monotonic()

    # ── 指纹管理 ──────────────────────────────────────────────────────────

    def update_fingerprint(self, fingerprint: str | None) -> None:
        """更新当前知识库指纹（由外部搜索管线在每次请求前调用）。

        传入 ``None`` 表示禁用指纹校验。
        """
        self._fingerprint = fingerprint

    @property
    def fingerprint(self) -> str | None:
        """当前知识库指纹（读通常量，由 ``update_fingerprint`` 写入）。"""
        return self._fingerprint

    # ── 公共 API ──────────────────────────────────────────────────────────

    def lookup(self, session_id: str, query_hash: str) -> Any | None:
        """返回 *session_id + query_hash* 对应的缓存值，未命中时返回 ``None``。

        过期的条目在访问时惰性淘汰。
        知识库指纹不匹配的条目同样视为过期（会话内发生文档变更时自动失效）。

        Args:
            session_id: 会话标识符（用于会话绑定缓存键）。
            query_hash: 查询文本的哈希值。

        Returns:
            缓存命中时返回存储的值，未命中时返回 None。
            调用方负责将返回值转换为预期类型。
        """
        # ── 会话绑定缓存查找 ──
        composite_key = self._make_composite_key(session_id, query_hash)
        entry = self._store.get(composite_key)
        if entry is None:
            self._stats["misses"] += 1
            self._logger.debug("cache_miss_l1", session_id=session_id, query_hash=query_hash)
            return None

        inserted_at, entry_ttl, result, stored_fp = self._unpack_l1(entry)
        if time.monotonic() - inserted_at > entry_ttl:
            del self._store[composite_key]
            self._stats["expirations"] += 1
            self._stats["misses"] += 1
            self._logger.debug(
                "cache_entry_expired",
                session_id=session_id,
                query_hash=query_hash,
            )
            return None

        # ── 指纹校验 ──
        # 同一会话内可能发生文档上传/删除/替换操作，
        # 导致知识库指纹变化。指纹不匹配 → 惰性淘汰（视为过期）。
        if not self._fingerprint_matches(stored_fp):
            del self._store[composite_key]
            self._stats["fingerprint_mismatches"] += 1
            self._stats["misses"] += 1
            self._logger.debug(
                "cache_invalidated_by_fingerprint",
                session_id=session_id,
                query_hash=query_hash,
                stored_fp=stored_fp,
                current_fp=self._fingerprint,
            )
            return None

        # LRU：移到末尾（最近使用）
        self._store.move_to_end(composite_key)
        self._stats["hits"] += 1
        self._logger.debug(
            "cache_hit_l1",
            session_id=session_id,
            query_hash=query_hash,
        )
        return result

    def store(
        self,
        session_id: str,
        query_hash: str,
        result: Any,
        *,
        ttl_override: float | None = None,
        zero_vector: bool = False,
    ) -> None:
        """以 *session_id + query_hash* 为复合键存储任意值。

        容量满时淘汰最久未使用的条目。
        写入时携带当前知识库指纹（若已注入）。

        Args:
            session_id: 会话标识符。
            query_hash: 查询文本的哈希值。
            result: 要缓存的任意值（RewriteResult、SearchResponse 等）。
            ttl_override: 条目级 TTL（秒）。为 ``None`` 时回退到实例默认 TTL。
            zero_vector: 查询向量为零向量时跳过缓存写入（不进入 L1/L2）。
        """
        if zero_vector:
            self._logger.debug(
                "zero_vector_skip_cache",
                session_id=session_id,
                query_hash=query_hash,
                cache_level="L1",
            )
            return

        composite_key = self._make_composite_key(session_id, query_hash)

        if composite_key in self._store:
            self._store.move_to_end(composite_key)

        effective_ttl = ttl_override if ttl_override is not None else self._ttl
        self._store[composite_key] = (time.monotonic(), effective_ttl, result, self._fingerprint)

        while len(self._store) > self._max_size:
            evicted_key, _ = self._store.popitem(last=False)
            self._stats["evictions"] += 1
            self._logger.debug("cache_evicted", composite_key=evicted_key)

        self._write_count += 1
        self._maybe_sweep()
        self._maybe_log_stats()

        self._logger.debug(
            "cache_stored",
            session_id=session_id,
            query_hash=query_hash,
        )

    def clear(self) -> None:
        """清空所有缓存条目（L1 和 L2）。"""
        self._store.clear()
        self._l2_store.clear()

    def clear_l1(self) -> None:
        """清空所有 L1 缓存条目（保留 L2 语义缓存）。

        文档状态变更（上传/删除/替换）时调用，确保已删除文档的
        内容不会通过会话缓存被返回。L2 由指纹校验机制独立保护。
        """
        self._store.clear()

    def invalidate_session(self, session_id: str) -> int:
        """清除指定会话的所有 L1 缓存条目（事件驱动失效）。

        当文档状态变更（上传/删除/替换）时由文件操作 API 调用，
        防止已删除文档的内容通过 L1 会话缓存被返回。

        仅清除 L1（会话绑定缓存），L2（跨会话语义缓存）由指纹校验
        机制独立处理。

        Args:
            session_id: 要失效的会话标识符。

        Returns:
            移除的 L1 条目数。
        """
        prefix = f"{session_id}:"
        keys_to_remove = [k for k in self._store if k.startswith(prefix)]
        for key in keys_to_remove:
            del self._store[key]
        if keys_to_remove:
            self._logger.debug(
                "cache_session_invalidated",
                session_id=session_id,
                removed_count=len(keys_to_remove),
            )
        return len(keys_to_remove)

    # ── L2 语义缓存（跨会话）────────────────────────────────────────────

    def store_l2(
        self,
        query_text: str,
        result: Any,
        *,
        knowledge_type: str = "general_knowledge",
        session_id: str | None = None,
        ttl_override: float | None = None,
        zero_vector: bool = False,
    ) -> None:
        """将重写结果存入 L2 精确文本缓存（跨会话）。

        使用规范化后的查询文本作为 Key 进行精确匹配（逐字符比较）。
        当前实现为精确文本匹配；向量语义检索（余弦相似度 > 0.95）
        已规划为后续迭代。

        knowledge_type 区分 ``"general_knowledge"``（可跨会话复用）和
        ``"context_dependent"``（仅限同会话 L1 复用）。

        写入时携带当前知识库指纹（若已注入）。

        Args:
            query_text: 查询文本（当前用于精确文本匹配 Key）。
            result: 缓存的重写结果。
            knowledge_type: ``"general_knowledge"`` 或 ``"context_dependent"``。
            session_id: 来源会话 ID（仅 context_dependent 需要，用于跨会话拦截）。
            ttl_override: 条目级 TTL（秒）。为 ``None`` 时回退到实例默认 TTL。
            zero_vector: 查询向量为零向量时跳过缓存写入（不进入 L1/L2）。
        """
        if zero_vector:
            self._logger.debug(
                "zero_vector_skip_cache",
                query_text=query_text,
                knowledge_type=knowledge_type,
                cache_level="L2",
            )
            return

        normalized = self._normalize_text(query_text)
        composite_key = self._make_l2_key(normalized)

        if composite_key in self._l2_store:
            self._l2_store.move_to_end(composite_key)

        effective_ttl = ttl_override if ttl_override is not None else self._ttl
        self._l2_store[composite_key] = (
            time.monotonic(),
            effective_ttl,
            result,
            knowledge_type,
            session_id,
            self._fingerprint,
        )

        while len(self._l2_store) > self._max_l2_size:
            evicted_key, _ = self._l2_store.popitem(last=False)
            self._stats["evictions"] += 1
            self._logger.debug("l2_cache_evicted", composite_key=evicted_key)

        self._logger.debug(
            "l2_cache_stored",
            normalized_query=normalized,
            knowledge_type=knowledge_type,
        )

    def lookup_l2(self, query_text: str) -> dict | None:
        """在 L2 精确文本缓存中查找与 *query_text* 匹配的条目。

        当前实现为规范化后的精确文本匹配（逐字符比较）。
        向量语义检索（余弦相似度 > 0.95）已规划为后续迭代。

        指纹不匹配的条目被视为过期（知识库已变更 → 旧跨会话缓存无效）。

        Args:
            query_text: 查询文本（用于精确文本匹配）。

        Returns:
            ``{"result": ..., "knowledge_type": ..., "source_session_id": ...}``
            或 ``None``（未命中）。
        """
        normalized = self._normalize_text(query_text)
        composite_key = self._make_l2_key(normalized)

        entry = self._l2_store.get(composite_key)
        if entry is None:
            self._stats["l2_misses"] += 1
            self._logger.debug("l2_cache_miss", normalized_query=normalized)
            return None

        inserted_at, entry_ttl, result, knowledge_type, session_id, stored_fp = self._unpack_l2(
            entry
        )
        if time.monotonic() - inserted_at > entry_ttl:
            del self._l2_store[composite_key]
            self._stats["expirations"] += 1
            self._stats["l2_misses"] += 1
            self._logger.debug("l2_entry_expired", normalized_query=normalized)
            return None

        # ── 指纹校验 ──
        if not self._fingerprint_matches(stored_fp):
            del self._l2_store[composite_key]
            self._stats["l2_fingerprint_mismatches"] += 1
            self._stats["l2_misses"] += 1
            self._logger.debug(
                "l2_cache_invalidated_by_fingerprint",
                normalized_query=normalized,
                stored_fp=stored_fp,
                current_fp=self._fingerprint,
            )
            return None

        # LRU: 移到末尾
        self._l2_store.move_to_end(composite_key)
        self._stats["l2_hits"] += 1
        self._logger.debug(
            "l2_cache_hit",
            normalized_query=normalized,
            knowledge_type=knowledge_type,
        )
        return {
            "result": result,
            "knowledge_type": knowledge_type,
            "source_session_id": session_id,
        }

    @property
    def l2_size(self) -> int:
        """当前 L2 缓存条目数。"""
        return len(self._l2_store)

    # ── 可观测性 ──────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """返回当前缓存统计快照。

        Returns:
            包含 hits, misses, l2_hits, l2_misses, evictions, expirations,
            sweep_removed, fingerprint_mismatches, l2_fingerprint_mismatches,
            size, l2_size, hit_rate 的字典。
        """
        total = self._stats["hits"] + self._stats["misses"]
        return {
            **self._stats,
            "size": self.size,
            "l2_size": self.l2_size,
            "hit_rate": round(self._stats["hits"] / total, 4) if total > 0 else 0.0,
        }

    # ── 写入时抽样清理（Redis active-expiration 模式）────────────────────

    def _maybe_sweep(self) -> None:
        """每 N 次写入触发一次随机抽样清理过期条目。

        检查 L1 和 L2（TTL 过期 + 指纹不匹配）两个存储的随机样本。
        """
        if self._write_count % self._CLEANUP_TRIGGER_EVERY_N != 0:
            return
        self._sweep_expired(self._store, "l1")
        self._sweep_expired(self._l2_store, "l2")

    def _sweep_expired(self, store: OrderedDict, label: str) -> int:
        """随机抽样清理 *store* 中的过期条目（TTL 过期 + 指纹不匹配）。

        Args:
            store: 要清理的 OrderedDict（L1 或 L2）。
            label: 存储标签，用于日志（``"l1"`` 或 ``"l2"``）。

        Returns:
            本次清理移除的条目数。
        """
        if not store:
            return 0

        keys = list(store.keys())
        if len(keys) <= self._CLEANUP_SAMPLE_SIZE:
            sample_keys = keys
        else:
            sample_keys = random.sample(keys, self._CLEANUP_SAMPLE_SIZE)

        now = time.monotonic()
        removed = 0
        for key in sample_keys:
            entry = store.get(key)
            if entry is None:
                continue
            # 兼容旧三元组（无指纹字段），此时 stored_fp 回退到 None
            unpacked = self._unpack_entry(entry, label)
            inserted_at = unpacked[0]
            entry_ttl = unpacked[1]
            stored_fp = unpacked[-1]
            expired = now - inserted_at > entry_ttl
            fp_mismatch = not self._fingerprint_matches(stored_fp)
            if expired or fp_mismatch:
                del store[key]
                removed += 1

        if removed:
            self._stats["sweep_removed"] += removed
            self._logger.debug(
                "cache_sweep_expired",
                label=label,
                removed=removed,
                sampled=len(sample_keys),
                total=len(store),
            )
        return removed

    # ── 统计快照日志 ──────────────────────────────────────────────────────

    def _maybe_log_stats(self) -> None:
        """定期输出缓存统计快照到结构化日志。

        每次写入时检查，距上次输出超过 ``_STATS_LOG_INTERVAL`` 秒时
        输出一条 ``cache_stats_snapshot`` 日志。
        """
        now = time.monotonic()
        if now - self._last_stats_log >= self._STATS_LOG_INTERVAL:
            self._logger.info("cache_stats_snapshot", **self.get_stats())
            self._last_stats_log = now

    # ── 属性 ─────────────────────────────────────────────────────────────

    @property
    def size(self) -> int:
        """当前 L1 缓存条目数（含尚未被惰性淘汰的过期条目）。"""
        return len(self._store)

    # ── 内部方法 ──────────────────────────────────────────────────────────

    def _fingerprint_matches(self, stored_fp: str | None) -> bool:
        """校验存储的指纹是否与当前指纹匹配。

        - 当前指纹为 ``None`` → 跳过校验（未启用），返回 True
        - 存储指纹为 ``None`` → 旧条目（无指纹），允许通过（向后兼容）
        - 两者都不为 None → 必须完全相等
        """
        if self._fingerprint is None:
            return True
        if stored_fp is None:
            return True  # 旧格式条目，向上兼容
        return stored_fp == self._fingerprint

    @staticmethod
    def _unpack_l1(entry: tuple) -> tuple:
        """解包 L1 条目，兼容旧三元组（无指纹）。"""
        if len(entry) == 3:
            return (entry[0], entry[1], entry[2], None)
        return entry  # 四元组: (ts, ttl, value, fp)

    @staticmethod
    def _unpack_l2(entry: tuple) -> tuple:
        """解包 L2 条目，兼容旧五元组（无指纹）。"""
        if len(entry) == 5:
            return (entry[0], entry[1], entry[2], entry[3], entry[4], None)
        return entry  # 六元组: (ts, ttl, value, kt, sid, fp)

    @staticmethod
    def _unpack_entry(entry: tuple, label: str) -> tuple:
        """通用解包，根据 label 分发到 L1 或 L2 的解包逻辑。"""
        if label == "l1":
            return CacheManager._unpack_l1(entry)
        return CacheManager._unpack_l2(entry)

    @staticmethod
    def _make_composite_key(session_id: str, query_hash: str) -> str:
        """构造会话绑定的复合缓存键。

        格式：``{session_id}:{query_hash}``
        """
        return f"{session_id}:{query_hash}"

    @staticmethod
    def _make_l2_key(normalized_query: str) -> str:
        """构造 L2 语义缓存的键（跨会话，不绑定 session_id）。

        格式：``l2:{normalized_query}``
        当前使用规范化文本精确匹配，生产环境将替换为向量最近邻检索。
        """
        return f"l2:{normalized_query}"

    @staticmethod
    def _normalize_text(text: str) -> str:
        """规范化文本用于 L2 语义匹配。

        当前实现：trim + 小写 + 单空格化空白。
        生产环境中可替换为更复杂的规范化（去停用词、词干提取等）。
        """
        return " ".join(text.strip().lower().split())
