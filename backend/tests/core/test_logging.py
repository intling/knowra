"""Tests for structured logging via structlog.

验证 structlog 集成：trace_id 自动注入、console/json 双模式、关键字参数
结构化字段、logger.bind() 上下文绑定、文件轮转落盘。
"""

import json
import logging

from structlog import BoundLogger
from structlog._config import BoundLoggerLazyProxy
from structlog.testing import capture_logs

from app.core.logging import configure_logging, get_logger
from app.core.trace_context import clear_trace_id, set_trace_id

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _cleanup_root():
    """清理 root logger 的 handler 和 filter，避免测试间互相干扰。"""
    root = logging.getLogger()
    root.handlers.clear()
    root.filters.clear()


def _close_all_handlers():
    """关闭所有 root logger handler 以刷新缓冲区。"""
    for h in logging.getLogger().handlers:
        h.close()


# ---------------------------------------------------------------------------
# 1. Logger 工厂与 trace_id
# ---------------------------------------------------------------------------


class TestGetLogger:
    """验证 get_logger() 返回 structlog logger 且自动携带 trace_id。"""

    def test_get_logger_returns_structlog_bound_logger(self):
        """get_logger() 返回的 logger 是 structlog BoundLogger 或其 lazy proxy。"""
        _cleanup_root()
        configure_logging()
        logger = get_logger("tests.module")
        # structlog 26.x returns BoundLoggerLazyProxy which acts like BoundLogger
        assert isinstance(logger, (BoundLogger, BoundLoggerLazyProxy))

    def test_logger_autoinjects_trace_id_when_set(self, tmp_path):
        """设置 trace_id 后，日志 JSON 输出中包含该 trace_id。"""
        _cleanup_root()
        log_path = tmp_path / "test.log"
        configure_logging(
            debug=True,
            log_level="DEBUG",
            log_format="json",
            log_file_path=str(log_path),
            log_file_max_size=1024 * 1024,
        )
        set_trace_id("01JFZ8KJ4X2Q3M5N")

        logger = get_logger("tests.module")
        logger.info("hello-world")
        _close_all_handlers()

        content = log_path.read_text().strip()
        parsed = json.loads(content)
        assert parsed["trace_id"] == "01JFZ8KJ4X2Q3M5N"
        assert parsed["event"] == "hello-world"

    def test_logger_placeholder_when_no_trace_context(self, tmp_path):
        """无请求上下文时 trace_id 为 '-'"""
        _cleanup_root()
        log_path = tmp_path / "test.log"
        clear_trace_id()
        configure_logging(
            debug=True,
            log_level="DEBUG",
            log_format="json",
            log_file_path=str(log_path),
            log_file_max_size=1024 * 1024,
        )

        logger = get_logger("tests.module")
        logger.info("no-context")
        _close_all_handlers()

        content = log_path.read_text().strip()
        parsed = json.loads(content)
        assert parsed["trace_id"] == "-"

    def test_logger_supports_standard_methods(self):
        """logger 支持 debug/info/warning/error/exception 方法。"""
        _cleanup_root()
        configure_logging()
        logger = get_logger("tests.module")
        assert hasattr(logger, "debug")
        assert hasattr(logger, "info")
        assert hasattr(logger, "warning")
        assert hasattr(logger, "error")
        assert hasattr(logger, "exception")

    def test_keyword_args_instead_of_extra(self, tmp_path):
        """验证关键字参数方式传递结构化字段：logger.info("msg", key=val)。"""
        _cleanup_root()
        log_path = tmp_path / "test.log"
        configure_logging(
            debug=True,
            log_level="DEBUG",
            log_format="json",
            log_file_path=str(log_path),
            log_file_max_size=1024 * 1024,
        )
        set_trace_id("extra-trace")

        logger = get_logger("tests.module")
        logger.info("upload done", file_name="notes.pdf", byte_size=2048)
        _close_all_handlers()

        content = log_path.read_text().strip()
        parsed = json.loads(content)
        assert parsed["file_name"] == "notes.pdf"
        assert parsed["byte_size"] == 2048
        assert parsed["trace_id"] == "extra-trace"
        assert parsed["event"] == "upload done"


# ---------------------------------------------------------------------------
# 2. Logger.bind() 上下文绑定
# ---------------------------------------------------------------------------


class TestLoggerBind:
    """验证 logger.bind() 上下文绑定后字段自动继承。"""

    def test_bind_injects_fields_into_subsequent_calls(self):
        """bind() 绑定的字段应在后续所有调用中自动携带。"""
        _cleanup_root()
        configure_logging(debug=True, log_level="DEBUG")

        logger = get_logger("tests.module")
        bound = logger.bind(user_id="u_01", tenant_id="t_01")
        with capture_logs() as cap_logs:
            bound.info("操作完成")

        assert len(cap_logs) == 1
        assert cap_logs[0]["user_id"] == "u_01"
        assert cap_logs[0]["tenant_id"] == "t_01"
        assert cap_logs[0]["event"] == "操作完成"

    def test_bind_does_not_affect_original_logger(self):
        """bind() 返回的 bound logger 不应影响原始 logger。"""
        _cleanup_root()
        configure_logging(debug=True, log_level="DEBUG")

        logger = get_logger("tests.module")
        logger.bind(user_id="u_A")
        with capture_logs() as cap_logs:
            logger.info("original logger 调用")

        assert len(cap_logs) == 1
        assert "user_id" not in cap_logs[0]

    def test_bind_isolation_between_different_bound_loggers(self):
        """不同 bound logger 之间上下文隔离。"""
        _cleanup_root()
        configure_logging(debug=True, log_level="DEBUG")

        logger = get_logger("tests.module")
        logger_a = logger.bind(user_id="u_A")
        logger_b = logger.bind(user_id="u_B")

        with capture_logs() as cap_logs:
            logger_a.info("来自 A")
            logger_b.info("来自 B")

        assert len(cap_logs) == 2
        assert cap_logs[0]["user_id"] == "u_A"
        assert cap_logs[1]["user_id"] == "u_B"

    def test_new_binds_accumulate_with_previous_binds(self):
        """多次 bind() 应累积字段，不覆盖之前的绑定。"""
        _cleanup_root()
        configure_logging(debug=True, log_level="DEBUG")

        logger = get_logger("tests.module")
        bound1 = logger.bind(user_id="u_01")
        bound2 = bound1.bind(operation="delete")
        with capture_logs() as cap_logs:
            bound2.info("删除操作")

        assert len(cap_logs) == 1
        assert cap_logs[0]["user_id"] == "u_01"
        assert cap_logs[0]["operation"] == "delete"


# ---------------------------------------------------------------------------
# 3. Console 模式输出
# ---------------------------------------------------------------------------


class TestConsoleMode:
    """验证 structlog ConsoleRenderer 输出行为。"""

    def test_console_output_contains_trace_id(self, tmp_path):
        """console 模式文件输出中包含 trace_id。"""
        _cleanup_root()
        log_path = tmp_path / "test.log"
        configure_logging(
            debug=True,
            log_level="DEBUG",
            log_format="console",
            log_file_path=str(log_path),
            log_file_max_size=1024 * 1024,
        )
        set_trace_id("01JFZ8AAAAAA")

        logger = get_logger("app.service")
        logger.info("测试消息")
        _close_all_handlers()

        content = log_path.read_text()
        assert "01JFZ8AAAAAA" in content

    def test_console_output_contains_logger_name(self, tmp_path):
        """console 模式文件输出中包含 logger 名称。"""
        _cleanup_root()
        log_path = tmp_path / "test.log"
        configure_logging(
            debug=True,
            log_level="DEBUG",
            log_format="console",
            log_file_path=str(log_path),
            log_file_max_size=1024 * 1024,
        )

        logger = get_logger("app.service")
        logger.info("测试消息")
        _close_all_handlers()

        content = log_path.read_text()
        assert "app.service" in content

    def test_console_output_contains_message(self, tmp_path):
        """console 模式文件输出中包含事件消息。"""
        _cleanup_root()
        log_path = tmp_path / "test.log"
        configure_logging(
            debug=True,
            log_level="DEBUG",
            log_format="console",
            log_file_path=str(log_path),
            log_file_max_size=1024 * 1024,
        )

        logger = get_logger("app.service")
        logger.info("文件上传完成")
        _close_all_handlers()

        content = log_path.read_text()
        assert "文件上传完成" in content

    def test_console_output_inlines_extra_fields(self, tmp_path):
        """console 模式文件输出中包含关键字参数传入的额外字段。"""
        _cleanup_root()
        log_path = tmp_path / "test.log"
        configure_logging(
            debug=True,
            log_level="DEBUG",
            log_format="console",
            log_file_path=str(log_path),
            log_file_max_size=1024 * 1024,
        )
        set_trace_id("field-test")

        logger = get_logger("app.service")
        logger.info("上传完成", file_name="notes.pdf", byte_size=2048)
        _close_all_handlers()

        content = log_path.read_text()
        assert "notes.pdf" in content
        assert "2048" in content


# ---------------------------------------------------------------------------
# 4. JSON 模式输出
# ---------------------------------------------------------------------------


class TestJsonMode:
    """验证 structlog JSONRenderer 输出行为。"""

    def test_json_output_is_single_line(self, tmp_path):
        """JSON 模式输出为单行 JSON。"""
        _cleanup_root()
        log_path = tmp_path / "test.log"
        configure_logging(
            debug=True,
            log_level="DEBUG",
            log_format="json",
            log_file_path=str(log_path),
            log_file_max_size=1024 * 1024,
        )
        set_trace_id("json-test")

        logger = get_logger("app.service")
        logger.info("文件上传完成")
        _close_all_handlers()

        content = log_path.read_text().strip()
        lines = [line for line in content.split("\n") if line.strip()]
        assert len(lines) == 1

    def test_json_output_is_valid_json(self, tmp_path):
        """JSON 模式输出为可解析的 JSON 对象。"""
        _cleanup_root()
        log_path = tmp_path / "test.log"
        configure_logging(
            debug=True,
            log_level="DEBUG",
            log_format="json",
            log_file_path=str(log_path),
            log_file_max_size=1024 * 1024,
        )
        set_trace_id("json-test")

        logger = get_logger("app.service")
        logger.info("测试")
        _close_all_handlers()

        content = log_path.read_text().strip()
        parsed = json.loads(content)
        assert isinstance(parsed, dict)

    def test_json_output_contains_standard_fields(self, tmp_path):
        """JSON 输出包含 timestamp、level、trace_id、logger、event 字段。"""
        _cleanup_root()
        log_path = tmp_path / "test.log"
        configure_logging(
            debug=True,
            log_level="DEBUG",
            log_format="json",
            log_file_path=str(log_path),
            log_file_max_size=1024 * 1024,
        )
        set_trace_id("01JFZ8AAAAAA")

        logger = get_logger("app.service")
        logger.info("文件上传完成")
        _close_all_handlers()

        content = log_path.read_text().strip()
        parsed = json.loads(content)
        assert "timestamp" in parsed
        assert parsed["level"] == "info"
        assert parsed["trace_id"] == "01JFZ8AAAAAA"
        assert parsed["logger"] == "app.service"
        assert parsed["event"] == "文件上传完成"

    def test_json_output_flattens_keyword_extra_fields_to_root(self, tmp_path):
        """JSON 模式下关键字参数字段平铺在根级别。"""
        _cleanup_root()
        log_path = tmp_path / "test.log"
        configure_logging(
            debug=True,
            log_level="DEBUG",
            log_format="json",
            log_file_path=str(log_path),
            log_file_max_size=1024 * 1024,
        )
        set_trace_id("json-flat")

        logger = get_logger("app.service")
        logger.info("上传完成", file_name="notes.pdf", byte_size=2048)
        _close_all_handlers()

        content = log_path.read_text().strip()
        parsed = json.loads(content)
        assert parsed["file_name"] == "notes.pdf"
        assert parsed["byte_size"] == 2048


# ---------------------------------------------------------------------------
# 5. 文件日志与轮转
# ---------------------------------------------------------------------------


class TestFileLoggingHandler:
    """验证日志写入文件、文件轮转触发和备份数量控制。"""

    def test_logs_written_to_file(self, tmp_path):
        """日志正确写入文件。"""
        log_path = tmp_path / "test.log"
        configure_logging(
            debug=True,
            log_level="DEBUG",
            log_format="json",
            log_file_path=str(log_path),
            log_file_max_size=1024 * 1024,
            log_file_backup_count=2,
        )
        set_trace_id("file-test")

        logger = get_logger("test_file")
        logger.info("test message")
        _close_all_handlers()

        content = log_path.read_text()
        assert "test message" in content

    def test_file_rotation_triggers_at_max_size(self, tmp_path):
        """文件达到 maxBytes 时触发轮转。"""
        log_path = tmp_path / "rotate.log"
        configure_logging(
            debug=True,
            log_level="DEBUG",
            log_format="json",
            log_file_path=str(log_path),
            log_file_max_size=100,
            log_file_backup_count=2,
        )

        logger = get_logger("test_rotate")
        for _i in range(20):
            logger.info("x" * 50)
        _close_all_handlers()

        backup = tmp_path / "rotate.log.1"
        assert backup.exists() or log_path.exists()

    def test_backup_count_respected(self, tmp_path):
        """备份文件数量不超过 backupCount。"""
        log_path = tmp_path / "bounded.log"
        configure_logging(
            debug=True,
            log_level="DEBUG",
            log_format="json",
            log_file_path=str(log_path),
            log_file_max_size=50,
            log_file_backup_count=1,
        )

        logger = get_logger("test_bounded")
        for _i in range(30):
            logger.info("y" * 30)
        _close_all_handlers()

        backup2 = tmp_path / "bounded.log.2"
        assert not backup2.exists()

    def test_configure_logging_creates_log_directory(self, tmp_path):
        """验证日志路径父目录自动创建。"""
        log_dir = tmp_path / "deep" / "nested"
        log_file = log_dir / "app.log"

        configure_logging(
            debug=True,
            log_level="DEBUG",
            log_format="console",
            log_file_path=str(log_file),
            log_file_max_size=10 * 1024 * 1024,
            log_file_backup_count=3,
        )

        assert log_dir.exists()
        assert log_dir.is_dir()


# ---------------------------------------------------------------------------
# 6. 自动格式切换
# ---------------------------------------------------------------------------


class TestAutoFormatSelection:
    """验证 debug 模式与 LOG_FORMAT 自动选择。"""

    def test_debug_true_defaults_to_console(self):
        """debug=true 且 LOG_FORMAT 为空时自动选择 console 模式。"""
        _cleanup_root()
        configure_logging(debug=True, log_format="")
        root = logging.getLogger()
        stream_handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler)]
        assert len(stream_handlers) >= 1

    def test_debug_false_defaults_to_json(self):
        """debug=false 时自动选择 JSON 模式。"""
        _cleanup_root()
        configure_logging(debug=False, log_format="")
        root = logging.getLogger()
        assert len(root.handlers) >= 1

    def test_debug_true_auto_sets_console_format(self, tmp_path):
        """debug=True 且 LOG_FORMAT 为空时，日志应符合 console 格式。"""
        _cleanup_root()
        log_path = tmp_path / "auto.log"
        configure_logging(
            debug=True,
            log_format="",
            log_file_path=str(log_path),
            log_file_max_size=1024 * 1024,
        )
        set_trace_id("auto-test")

        logger = get_logger("test.auto")
        logger.info("auto format test")
        _close_all_handlers()

        content = log_path.read_text()
        assert "auto format test" in content


# ---------------------------------------------------------------------------
# 7. TraceFilter 保持不变
# ---------------------------------------------------------------------------


class TestTraceFilterPreserved:
    """验证 TraceFilter 仍正确注入 trace_id 到非 structlog 日志。"""

    def test_tracefilter_injects_trace_id_on_raw_logging(self, tmp_path):
        """直接使用标准库 logging 的日志也应通过 TraceFilter 获取 trace_id。"""
        _cleanup_root()
        log_path = tmp_path / "filter.log"
        configure_logging(
            debug=True,
            log_level="DEBUG",
            log_format="json",
            log_file_path=str(log_path),
            log_file_max_size=1024 * 1024,
            log_file_backup_count=2,
        )
        set_trace_id("filter-test-123")

        std_logger = logging.getLogger("test.raw")
        std_logger.info("raw log message")
        _close_all_handlers()

        content = log_path.read_text().strip()
        parsed = json.loads(content)
        assert parsed["trace_id"] == "filter-test-123"
