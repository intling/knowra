"""Circuit Breaker 熔断器单元测试。

测试覆盖：
- 连续失败 N 次（默认 5 次）后自动断开
- 断开期间所有请求跳过重写（快速失败，不执行实际操作）
- 冷却期满后半开探测成功恢复（circuit → closed）
- 探测失败重新断开（half_open → open）
- 成功调用重置失败计数器
- 可配置阈值和冷却时间
- 状态转换的正确性

设计参考 design.md Decision 中风险项"LLM 依赖增加"第 2 点：
    连续 N 次重写失败（建议 5 次）后，自动禁用重写模块
    QUERY_REWRITE_CIRCUIT_BREAKER_COOLDOWN_SECONDS 秒（建议 30s），
    期间所有请求使用原始查询。冷却期满后进入半开状态，
    允许 1 次探测请求通过——成功则恢复，失败则重新断开。
"""

from __future__ import annotations

import time

import pytest

from app.services.circuit_breaker import CircuitBreaker, CircuitState

# ═══════════════════════════════════════════════════════════════════════════════
# 辅助：模拟时间推进
# ═══════════════════════════════════════════════════════════════════════════════


class _FakeClock:
    """可手动控制的时间源，用于测试熔断器的冷却/半开逻辑。"""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


# ═══════════════════════════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════════════════════════


class TestCircuitBreakerInitialState:
    """初始状态验证。"""

    def test_initial_state_is_closed(self):
        """新创建的熔断器初始状态应为 CLOSED。"""
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED

    def test_initial_failure_count_is_zero(self):
        """新创建的熔断器失败计数应为 0。"""
        cb = CircuitBreaker()
        assert cb.failure_count == 0

    def test_before_call_returns_true_when_closed(self):
        """CLOSED 状态下 before_call() 应返回 True（允许调用）。"""
        cb = CircuitBreaker()
        assert cb.before_call() is True


class TestCircuitBreakerFailureCounting:
    """失败计数与断开逻辑。"""

    def test_failure_count_increments_on_failure(self):
        """每次 on_failure() 调用应递增失败计数器。"""
        cb = CircuitBreaker()
        cb.on_failure()
        assert cb.failure_count == 1
        cb.on_failure()
        assert cb.failure_count == 2

    def test_circuit_opens_after_threshold_failures(self):
        """连续失败达到阈值后熔断器应切换到 OPEN 状态。"""
        cb = CircuitBreaker(failure_threshold=5)
        for _ in range(5):
            cb.on_failure()
        assert cb.state == CircuitState.OPEN

    def test_circuit_opens_after_threshold_with_default(self):
        """使用默认阈值（5 次），连续失败 5 次后断开。"""
        cb = CircuitBreaker()
        for _ in range(5):
            cb.on_failure()
        assert cb.state == CircuitState.OPEN

    def test_circuit_opens_after_custom_threshold(self):
        """使用自定义阈值（3 次），连续失败 3 次后断开。"""
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.on_failure()
        assert cb.state == CircuitState.OPEN

    def test_circuit_stays_closed_below_threshold(self):
        """失败次数未达到阈值时，熔断器保持 CLOSED。"""
        cb = CircuitBreaker(failure_threshold=5)
        for _ in range(4):
            cb.on_failure()
        assert cb.state == CircuitState.CLOSED


class TestCircuitBreakerOpenState:
    """OPEN 状态下的行为验证。"""

    def make_open_breaker(
        self, failure_threshold: int = 5, cooldown_seconds: float = 30.0
    ) -> CircuitBreaker:
        """创建一个已断开的熔断器，用于测试 OPEN 状态行为。"""
        cb = CircuitBreaker(
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
        )
        for _ in range(failure_threshold):
            cb.on_failure()
        assert cb.state == CircuitState.OPEN
        return cb

    def test_before_call_returns_false_when_open(self):
        """OPEN 状态下 before_call() 应返回 False（拒绝调用）。"""
        cb = self.make_open_breaker()
        assert cb.before_call() is False

    def test_open_state_immediately_rejects_all_calls(self):
        """断开期间所有请求都应被立即拒绝，不执行实际操作。"""
        cb = self.make_open_breaker()
        for _ in range(10):
            assert cb.before_call() is False

    def test_failure_count_unchanged_during_open(self):
        """OPEN 状态下调用 on_failure() 不改变失败计数。"""
        cb = self.make_open_breaker(failure_threshold=5)
        count_before = cb.failure_count
        cb.on_failure()
        assert cb.failure_count == count_before

    def test_on_success_noop_during_open(self):
        """OPEN 状态下 on_success() 不应将状态切回 CLOSED。"""
        cb = self.make_open_breaker()
        cb.on_success()
        assert cb.state == CircuitState.OPEN


class TestCircuitBreakerHalfOpenProbe:
    """半开探测逻辑验证。"""

    # ── 辅助：创建进入 HALF_OPEN 的熔断器 ──

    @staticmethod
    def make_half_open_breaker(
        monkeypatch,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
        *,
        clock: _FakeClock | None = None,
    ) -> tuple[CircuitBreaker, _FakeClock]:
        """创建一个已进入 HALF_OPEN 状态的熔断器。

        步骤：
        1. 创建熔断器，连续触发 failure_threshold 次失败使其 OPEN
        2. 使用假时钟推进 cooldown_seconds + 1 秒
        3. 下一次 before_call() 应触发 HALF_OPEN 转换

        Returns:
            (circuit_breaker, fake_clock) 元组。
        """
        if clock is None:
            clock = _FakeClock()

        monkeypatch.setattr(time, "monotonic", clock)

        cb = CircuitBreaker(
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
        )
        # 触发足够次数失败使其进入 OPEN 状态
        for _ in range(failure_threshold):
            cb.on_failure()
        assert cb.state == CircuitState.OPEN

        # 推进时间使冷却期过期
        clock.advance(cooldown_seconds + 1.0)

        # 首次 before_call() 应触发 HALF_OPEN
        can_call = cb.before_call()
        assert can_call is True, "冷却期满后应允许探测请求"
        assert cb.state == CircuitState.HALF_OPEN
        return cb, clock

    # ── 测试用例 ──

    def test_transitions_to_half_open_after_cooldown(self, monkeypatch):
        """冷却期满后首次 before_call() 应从 OPEN 切换到 HALF_OPEN。"""
        clock = _FakeClock()
        monkeypatch.setattr(time, "monotonic", clock)

        cb = CircuitBreaker(failure_threshold=5, cooldown_seconds=30.0)
        for _ in range(5):
            cb.on_failure()
        assert cb.state == CircuitState.OPEN

        # 冷却期未满 → 仍拒绝
        clock.advance(10.0)
        assert cb.before_call() is False
        assert cb.state == CircuitState.OPEN

        # 冷却期满 → 半开
        clock.advance(21.0)  # total = 31s > 30s
        assert cb.before_call() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_transitions_to_closed(self, monkeypatch):
        """HALF_OPEN 状态下探测成功 → 切换回 CLOSED，失败计数清零。"""
        cb, _clock = self.make_half_open_breaker(monkeypatch)

        # 探测成功
        cb.on_success()

        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_half_open_failure_transitions_back_to_open(self, monkeypatch):
        """HALF_OPEN 状态下探测失败 → 重新断开（OPEN），重置冷却期。"""
        cb, clock = self.make_half_open_breaker(monkeypatch)

        # 探测失败
        cb.on_failure()

        assert cb.state == CircuitState.OPEN

        # 推进冷却期后再次半开
        clock.advance(31.0)
        assert cb.before_call() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_only_allows_one_probe(self, monkeypatch):
        """HALF_OPEN 状态只允许一次探测请求，后续请求被拒绝。"""
        cb, _clock = self.make_half_open_breaker(monkeypatch)

        # 第一次调用（探测）已通过 make_half_open_breaker 中的 before_call() 完成
        # 第二次调用应被拒绝（仅一个探测名额）
        assert cb.before_call() is False

    def test_half_open_probe_success_resets_and_allows_next_call(self, monkeypatch):
        """探测成功后，后续调用应正常通过（CLOSED 状态）。"""
        cb, _clock = self.make_half_open_breaker(monkeypatch)

        # 探测成功
        cb.on_success()
        assert cb.state == CircuitState.CLOSED

        # 后续调用正常通过
        assert cb.before_call() is True

    def test_half_open_after_success_subsequent_failures_count_normally(self, monkeypatch):
        """从 HALF_OPEN 恢复为 CLOSED 后，新的失败从 0 开始计数。"""
        cb, _clock = self.make_half_open_breaker(monkeypatch)

        # 探测成功 → CLOSED
        cb.on_success()

        # 新失败从 0 开始
        cb.on_failure()
        assert cb.failure_count == 1
        cb.on_failure()
        assert cb.failure_count == 2
        # 不会因为之前的历史计数而立即断开
        assert cb.state == CircuitState.CLOSED


class TestCircuitBreakerSuccessResets:
    """成功调用重置失败计数器。"""

    def test_success_resets_failure_count_in_closed_state(self):
        """CLOSED 状态下成功调用将失败计数归零。"""
        cb = CircuitBreaker(failure_threshold=5)
        cb.on_failure()
        cb.on_failure()
        cb.on_failure()
        assert cb.failure_count == 3

        cb.on_success()
        assert cb.failure_count == 0

    def test_interleaved_success_prevents_opening(self):
        """失败和成功交替出现时，不应触发熔断（因为成功重置计数）。"""
        cb = CircuitBreaker(failure_threshold=5)
        for _ in range(10):
            cb.on_failure()
            cb.on_success()  # 每次成功后归零
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0


class TestCircuitBreakerConfiguration:
    """配置参数验证。"""

    def test_custom_failure_threshold(self):
        """自定义失败阈值应生效。"""
        cb = CircuitBreaker(failure_threshold=10)
        for _ in range(9):
            cb.on_failure()
        assert cb.state == CircuitState.CLOSED
        cb.on_failure()
        assert cb.state == CircuitState.OPEN

    def test_custom_cooldown_seconds(self, monkeypatch):
        """自定义冷却时间应生效。"""
        clock = _FakeClock()
        monkeypatch.setattr(time, "monotonic", clock)

        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=10.0)
        cb.on_failure()
        cb.on_failure()
        assert cb.state == CircuitState.OPEN

        # 冷却期未满（5s < 10s）
        clock.advance(5.0)
        assert cb.before_call() is False

        # 冷却期满（+6s = 11s > 10s）
        clock.advance(6.0)
        assert cb.before_call() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_zero_cooldown_immediate_half_open(self, monkeypatch):
        """冷却时间为 0 时应立即进入 HALF_OPEN。"""
        clock = _FakeClock()
        monkeypatch.setattr(time, "monotonic", clock)

        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.0)
        cb.on_failure()
        cb.on_failure()
        assert cb.state == CircuitState.OPEN

        # 无需等待即可进入 HALF_OPEN
        assert cb.before_call() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_negative_failure_threshold_raises(self):
        """负的失败阈值应抛出 ValueError。"""
        with pytest.raises(ValueError, match="failure_threshold"):
            CircuitBreaker(failure_threshold=-1)

    def test_negative_cooldown_raises(self):
        """负的冷却时间应抛出 ValueError。"""
        with pytest.raises(ValueError, match="cooldown_seconds"):
            CircuitBreaker(cooldown_seconds=-1.0)


class TestCircuitBreakerFullLifecycle:
    """完整的生命周期测试 —— 模拟真实的故障 → 恢复 → 再故障场景。"""

    def test_full_open_close_reopen_cycle(self, monkeypatch):
        """验证完整的 CLOSED → OPEN → HALF_OPEN → CLOSED → OPEN 生命周期。"""
        clock = _FakeClock()
        monkeypatch.setattr(time, "monotonic", clock)

        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=30.0)

        # Phase 1: CLOSED → 累积失败 → OPEN
        assert cb.state == CircuitState.CLOSED
        for _ in range(3):
            assert cb.before_call() is True  # CLOSED 允许调用
            cb.on_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 3

        # Phase 2: OPEN → 拒绝调用
        for _ in range(5):
            assert cb.before_call() is False

        # Phase 3: 冷却期满 → HALF_OPEN
        clock.advance(31.0)
        assert cb.before_call() is True
        assert cb.state == CircuitState.HALF_OPEN

        # Phase 4: 探测成功 → CLOSED
        cb.on_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

        # Phase 5: 再次累积失败 → OPEN
        for _ in range(3):
            cb.on_failure()
        assert cb.state == CircuitState.OPEN

    def test_full_open_half_open_failure_reopen_cycle(self, monkeypatch):
        """验证 OPEN → HALF_OPEN（探测失败）→ OPEN 的完整循环。"""
        clock = _FakeClock()
        monkeypatch.setattr(time, "monotonic", clock)

        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=30.0)

        # 触发断开
        for _ in range(3):
            cb.on_failure()
        assert cb.state == CircuitState.OPEN

        # 冷却期满 → 半开
        clock.advance(31.0)
        assert cb.before_call() is True
        assert cb.state == CircuitState.HALF_OPEN

        # 探测失败 → 重新断开
        cb.on_failure()
        assert cb.state == CircuitState.OPEN

        # 重新进入冷却期：立即调用被拒绝
        assert cb.before_call() is False

        # 冷却期再次满 → 第二次半开
        clock.advance(31.0)
        assert cb.before_call() is True
        assert cb.state == CircuitState.HALF_OPEN

        # 第二次探测成功
        cb.on_success()
        assert cb.state == CircuitState.CLOSED


class TestCircuitBreakerWithQueryRewriterIntegration:
    """验证熔断器与 QueryRewriter 的集成契约。

    这些测试验证 CircuitBreaker 的 API 签名和状态转换行为
    与 QueryRewriter.rewrite() 中预期的使用模式一致。

    QueryRewriter 中的集成模式：
        if not self._circuit_breaker.before_call():
            # 熔断器已断开 → 跳过重写，返回原始查询
            return RewriteResult(
                original_query=query,
                rewritten_queries=[{"query": query, "strategy": "direct"}],
                rewrite_model=effective_model,
            )
        try:
            result = await self._do_rewrite(...)
            self._circuit_breaker.on_success()
            return result
        except Exception:
            self._circuit_breaker.on_failure()
            # 降级返回原始查询
            ...
    """

    def test_integration_pattern_closed_state(self):
        """在 CLOSED 状态下验证集成调用模式。"""
        cb = CircuitBreaker(failure_threshold=5, cooldown_seconds=30.0)

        # before_call() 应允许通过
        assert cb.before_call() is True

        # 模拟成功调用
        cb.on_success()
        assert cb.state == CircuitState.CLOSED

    def test_integration_pattern_failure_opens_circuit(self):
        """连续失败导致熔断后，before_call() 应拒绝调用。"""
        cb = CircuitBreaker(failure_threshold=5, cooldown_seconds=30.0)

        # 连续失败 5 次
        for _ in range(5):
            assert cb.before_call() is True  # CLOSED 允许
            cb.on_failure()

        # 第 6 次调用被拒绝
        assert cb.before_call() is False
        assert cb.state == CircuitState.OPEN

    def test_integration_pattern_recovery_after_cooldown(self, monkeypatch):
        """冷却期满后探测成功应恢复。"""
        clock = _FakeClock()
        monkeypatch.setattr(time, "monotonic", clock)

        cb = CircuitBreaker(failure_threshold=5, cooldown_seconds=30.0)
        for _ in range(5):
            cb.on_failure()
        assert cb.state == CircuitState.OPEN

        # 冷却期满
        clock.advance(31.0)

        # 探测请求
        assert cb.before_call() is True
        assert cb.state == CircuitState.HALF_OPEN

        # 探测成功
        cb.on_success()
        assert cb.state == CircuitState.CLOSED

    def test_integration_pattern_only_before_call_advances_state(self, monkeypatch):
        """仅 before_call() 触发状态转换（OPEN→HALF_OPEN），on_failure/on_success 不主动转换。"""
        clock = _FakeClock()
        monkeypatch.setattr(time, "monotonic", clock)

        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=30.0)
        for _ in range(3):
            cb.on_failure()
        assert cb.state == CircuitState.OPEN

        # 推进时间但不调用 before_call() → 状态应仍为 OPEN
        clock.advance(31.0)
        # on_success / on_failure 不应更改 OPEN 状态
        cb.on_success()
        assert cb.state == CircuitState.OPEN  # 仍为 OPEN（无 before_call）

        # 只有 before_call() 触发 HALF_OPEN
        assert cb.before_call() is True
        assert cb.state == CircuitState.HALF_OPEN
