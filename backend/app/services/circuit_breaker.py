"""Circuit Breaker 熔断器 —— 连续失败自动断开，半开探测恢复。

实现设计参考 design.md Decision 风险项"LLM 依赖增加"第 2 点：
    连续 N 次重写失败（默认 5 次）后，自动禁用重写模块
    QUERY_REWRITE_CIRCUIT_BREAKER_COOLDOWN_SECONDS 秒（默认 30s），
    期间所有请求使用原始查询。冷却期满后进入半开状态，
    允许 1 次探测请求通过——成功则恢复，失败则重新断开。

Usage::

    cb = CircuitBreaker(failure_threshold=5, cooldown_seconds=30.0)

    if not cb.before_call():
        # 熔断器已断开 → 跳过操作，直接降级
        return fallback_result

    try:
        result = do_work()
        cb.on_success()
        return result
    except Exception:
        cb.on_failure()
        return fallback_result
"""

from __future__ import annotations

import time
from enum import Enum, auto


class CircuitState(Enum):
    """熔断器状态。"""

    CLOSED = auto()  # 正常：请求通过，失败计数
    OPEN = auto()  # 熔断：所有请求被拒，冷却中
    HALF_OPEN = auto()  # 半开：允许单次探测请求


class CircuitBreaker:
    """轻量级熔断器，无需第三方依赖。

    状态转换：:

        CLOSED ──(连续失败≥阈值)──→ OPEN
        OPEN   ──(冷却期满)──────→ HALF_OPEN (via before_call)
        HALF_OPEN ──(探测成功)───→ CLOSED
        HALF_OPEN ──(探测失败)───→ OPEN

    Args:
        failure_threshold: 连续失败次数阈值，达到后断开。必须 ≥ 0。
        cooldown_seconds: 熔断后冷却时间（秒）。期满后半开探测。必须 ≥ 0。
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
    ) -> None:
        if failure_threshold < 0:
            raise ValueError(f"failure_threshold must be >= 0, got {failure_threshold}")
        if cooldown_seconds < 0:
            raise ValueError(f"cooldown_seconds must be >= 0, got {cooldown_seconds}")

        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None
        self._half_open_probe_in_flight = False

    # ── 只读属性 ──────────────────────────────────────────────────────────

    @property
    def state(self) -> CircuitState:
        """当前熔断器状态。"""
        return self._state

    @property
    def failure_count(self) -> int:
        """当前连续失败计数。"""
        return self._failure_count

    # ── 公共 API ──────────────────────────────────────────────────────────

    def before_call(self) -> bool:
        """在操作执行前调用，判断是否允许通过。

        Returns:
            ``True`` 表示允许执行操作；``False`` 表示已被熔断应跳过操作。

        副作用:
            - OPEN 状态且冷却期满 → 自动转换到 HALF_OPEN 并占用探测名额。
            - HALF_OPEN 状态且探测名额已占用 → 返回 ``False``。
        """
        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.OPEN:
            if self._cooldown_expired():
                # 冷却期满 → 半开探测
                self._state = CircuitState.HALF_OPEN
                self._half_open_probe_in_flight = True
                return True
            return False

        # CircuitState.HALF_OPEN
        if self._half_open_probe_in_flight:
            # 探测请求已在飞行中，拒绝后续调用
            return False
        self._half_open_probe_in_flight = True
        return True

    def on_success(self) -> None:
        """操作成功时调用。

        副作用:
            - CLOSED 状态 → 失败计数归零。
            - HALF_OPEN 状态 → 切换回 CLOSED，失败计数归零。
            - OPEN 状态 → 无操作。
        """
        if self._state == CircuitState.CLOSED:
            self._failure_count = 0

        elif self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at = None
            self._half_open_probe_in_flight = False

        # OPEN: no-op

    def on_failure(self) -> None:
        """操作失败时调用。

        副作用:
            - CLOSED 状态 → 递增失败计数，达到阈值时切换到 OPEN。
            - HALF_OPEN 状态 → 探测失败，切换回 OPEN 并重置冷却。
            - OPEN 状态 → 无操作（计数不变）。
        """
        if self._state == CircuitState.CLOSED:
            self._failure_count += 1
            if self._failure_count >= self._failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                self._half_open_probe_in_flight = False

        elif self._state == CircuitState.HALF_OPEN:
            # 探测失败 → 重新熔断
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()
            self._half_open_probe_in_flight = False

        # OPEN: no-op — failure_count 保持不变

    # ── 内部方法 ──────────────────────────────────────────────────────────

    def _cooldown_expired(self) -> bool:
        """检查冷却期是否已过。"""
        if self._opened_at is None:
            return True
        return (time.monotonic() - self._opened_at) >= self._cooldown_seconds
