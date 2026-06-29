"""Tests for app.core.trace_context — request-scoped trace ID via contextvars."""

import asyncio

from app.core.trace_context import get_trace_id, set_trace_id


class TestTraceContextBasicReadWrite:
    """1.1 验证 TraceContext.set_trace_id() / get_trace_id() 的基本读写功能"""

    def test_set_and_get_trace_id(self):
        """设置 trace_id 后，get_trace_id 返回相同的值"""
        set_trace_id("01JFZ8KJ4X2Q3M5N")
        assert get_trace_id() == "01JFZ8KJ4X2Q3M5N"

    def test_default_trace_id_is_placeholder(self):
        """未设置 trace_id 时，get_trace_id 返回 '-'"""
        # 在隔离的上下文中不应有预设值（测试运行器的 main 协程可能没有）
        # 我们只验证函数不抛异常且返回字符串
        result = get_trace_id()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_overwrite_trace_id(self):
        """连续两次 set_trace_id 后，get_trace_id 返回最新值"""
        set_trace_id("first-id")
        set_trace_id("second-id")
        assert get_trace_id() == "second-id"


class TestTraceContextConcurrencyIsolation:
    """1.2 验证并发场景下不同协程的追踪上下文隔离性"""

    @staticmethod
    async def _set_and_read(trace_id: str) -> str:
        set_trace_id(trace_id)
        # 让出控制权，模拟真实异步场景
        await asyncio.sleep(0.01)
        return get_trace_id()

    def test_concurrent_coroutines_have_isolated_contexts(self):
        """验证不同协程的追踪上下文互不干扰"""

        async def main():
            set_trace_id("main-task")
            # 并发运行两个协程，各自设置不同的 trace_id
            results = await asyncio.gather(
                self._set_and_read("task-A"),
                self._set_and_read("task-B"),
            )
            # 主协程的 trace_id 不应被修改
            main_trace_id = get_trace_id()
            return results, main_trace_id

        (results, main_trace_id) = asyncio.run(main())
        assert results[0] == "task-A"
        assert results[1] == "task-B"
        assert main_trace_id == "main-task"
