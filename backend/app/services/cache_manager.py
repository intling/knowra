"""查询重写结果的内存 L1 精确缓存（绑定会话 ID）。

会话内缓存策略（模块一）：
    - 缓存 Key 绑定会话 ID：不同会话的相同问题不共享缓存
    - 精确匹配：仅当原始 Query 字符串逐字符完全一致时命中

不同会话的 L2 语义缓存策略（模块二）：
    - 基于语义向量检索，相似度 > 0.95 时考虑命中
    - 仅通用知识允许跨会话复用
    - 需经过上下文相关性校验后返回

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
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any

from app.core.logging import get_logger


class CacheManager:
    """类型无关的内存精确匹配（L1）缓存（会话绑定）。

    基于 OrderedDict 实现 LRU 淘汰策略，每条缓存条目有独立的 TTL。
    适用于 FastAPI 单线程异步事件循环模型；如需并发访问，请在外部
    使用 ``asyncio.Lock``。

    会话绑定：
        缓存键 = hash(session_id + query_hash)，确保不同会话的
        相同查询不会错误共享缓存结果。

    泛型使用：
        存储和返回类型为 ``Any``，调用方负责类型转换。
        典型用例：缓存 RewriteResult、SearchResponse 等。
    """

    def __init__(self, *, max_size: int = 1000, ttl_seconds: float = 3600.0) -> None:
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._logger = get_logger(__name__)

    # ── 公共 API ──────────────────────────────────────────────────────────

    def lookup(self, session_id: str, query_hash: str) -> Any | None:
        """返回 *session_id + query_hash* 对应的缓存值，未命中时返回 ``None``。

        过期的条目在访问时惰性淘汰。

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
            self._logger.debug("cache_miss_l1", session_id=session_id, query_hash=query_hash)
            return None

        inserted_at, result = entry
        if time.monotonic() - inserted_at > self._ttl:
            del self._store[composite_key]
            self._logger.debug(
                "cache_entry_expired",
                session_id=session_id,
                query_hash=query_hash,
            )
            return None

        # LRU：移到末尾（最近使用）
        self._store.move_to_end(composite_key)
        self._logger.debug(
            "cache_hit_l1",
            session_id=session_id,
            query_hash=query_hash,
        )
        return result

    def store(self, session_id: str, query_hash: str, result: Any) -> None:
        """以 *session_id + query_hash* 为复合键存储任意值。

        容量满时淘汰最久未使用的条目。

        Args:
            session_id: 会话标识符。
            query_hash: 查询文本的哈希值。
            result: 要缓存的任意值（RewriteResult、SearchResponse 等）。
        """
        composite_key = self._make_composite_key(session_id, query_hash)

        if composite_key in self._store:
            self._store.move_to_end(composite_key)

        self._store[composite_key] = (time.monotonic(), result)

        while len(self._store) > self._max_size:
            evicted_key, _ = self._store.popitem(last=False)
            self._logger.debug("cache_evicted", composite_key=evicted_key)

        self._logger.debug(
            "cache_stored",
            session_id=session_id,
            query_hash=query_hash,
        )

    def clear(self) -> None:
        """清空所有缓存条目。"""
        self._store.clear()

    # ── 属性 ─────────────────────────────────────────────────────────────

    @property
    def size(self) -> int:
        """当前缓存条目数（含尚未被惰性淘汰的过期条目）。"""
        return len(self._store)

    # ── 内部方法 ──────────────────────────────────────────────────────────

    @staticmethod
    def _make_composite_key(session_id: str, query_hash: str) -> str:
        """构造会话绑定的复合缓存键。

        格式：``{session_id}:{query_hash}``
        """
        return f"{session_id}:{query_hash}"
