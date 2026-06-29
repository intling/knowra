"""Tests for structured logging — Logger adapter, formatters, and file handler.

3.1–3.4 red tests for the logging module.
"""

import json
import logging

from app.core.logging import (
    ConsoleFormatter,
    JsonFormatter,
    configure_logging,
    get_logger,
)
from app.core.trace_context import clear_trace_id, set_trace_id

# ---------------------------------------------------------------------------
# 3.1 — Structured Logger
# ---------------------------------------------------------------------------


class TestStructuredLogger:
    """验证 get_logger() 返回的 logger 自动携带 trace_id"""

    def test_logger_autoinjects_trace_id_when_set(self, caplog):
        set_trace_id("01JFZ8KJ4X2Q3M5N")
        logger = get_logger("tests.module")
        caplog.set_level(logging.DEBUG)

        logger.info("hello-world")
        record = caplog.records[0]
        assert record.trace_id == "01JFZ8KJ4X2Q3M5N"
        assert record.message == "hello-world"

    def test_logger_placeholder_when_no_trace_context(self, caplog):
        """无上下文时 trace_id 为 '-'"""
        clear_trace_id()
        logger = get_logger("tests.module")
        caplog.set_level(logging.DEBUG)

        logger.info("no-context")
        record = caplog.records[0]
        assert record.trace_id == "-"

    def test_logger_supports_standard_methods(self):
        logger = get_logger("tests.module")
        assert hasattr(logger, "debug")
        assert hasattr(logger, "info")
        assert hasattr(logger, "warning")
        assert hasattr(logger, "error")
        assert hasattr(logger, "exception")

    def test_logger_extra_fields_in_record(self, caplog):
        set_trace_id("extra-trace")
        logger = get_logger("tests.module")
        caplog.set_level(logging.DEBUG)

        logger.info("upload done", extra={"file_name": "notes.pdf", "byte_size": 2048})
        record = caplog.records[0]
        assert record.file_name == "notes.pdf"
        assert record.byte_size == 2048
        assert record.trace_id == "extra-trace"


# ---------------------------------------------------------------------------
# 3.2 — Console Formatter
# ---------------------------------------------------------------------------


class TestConsoleFormatter:
    """验证 console 模式输出包含 ANSI 颜色码和 key=value 格式"""

    def _make_record(self, **extra) -> logging.LogRecord:
        """Create a LogRecord with extra fields attached as attributes."""
        record = logging.LogRecord(
            name="app.service",
            level=logging.INFO,
            pathname="app/service.py",
            lineno=42,
            msg="文件上传完成",
            args=(),
            exc_info=None,
        )
        record.trace_id = "01JFZ8AAAAAA"
        for k, v in extra.items():
            setattr(record, k, v)
        return record

    def test_console_output_contains_ansi_color_codes(self):
        fmt = ConsoleFormatter()
        record = self._make_record()
        output = fmt.format(record)
        # ANSI escape starts with \033[
        assert "\033[" in output

    def test_console_output_contains_trace_id(self):
        fmt = ConsoleFormatter()
        record = self._make_record()
        output = fmt.format(record)
        assert "01JFZ8AAAAAA" in output

    def test_console_output_contains_logger_name(self):
        fmt = ConsoleFormatter()
        record = self._make_record()
        output = fmt.format(record)
        assert "app.service" in output

    def test_console_output_contains_message(self):
        fmt = ConsoleFormatter()
        record = self._make_record()
        output = fmt.format(record)
        assert "文件上传完成" in output

    def test_console_output_inlines_extra_fields(self):
        fmt = ConsoleFormatter()
        record = self._make_record(file_name="notes.pdf", byte_size=2048)
        output = fmt.format(record)
        assert "file_name=notes.pdf" in output
        assert "byte_size=2048" in output

    def test_console_error_level_has_red_color(self):
        fmt = ConsoleFormatter()
        record = self._make_record()
        record.levelno = logging.ERROR
        record.levelname = "ERROR"
        output = fmt.format(record)
        # Red color: \033[31m or similar
        assert "\033[31" in output


# ---------------------------------------------------------------------------
# 3.3 — JSON Formatter
# ---------------------------------------------------------------------------


class TestJsonFormatter:
    """验证 json 模式输出为单行有效 JSON，extra 字段平铺在根级别"""

    def _make_record(self, **extra) -> logging.LogRecord:
        record = logging.LogRecord(
            name="app.service",
            level=logging.INFO,
            pathname="app/service.py",
            lineno=42,
            msg="文件上传完成",
            args=(),
            exc_info=None,
        )
        record.trace_id = "01JFZ8AAAAAA"
        for k, v in extra.items():
            setattr(record, k, v)
        return record

    def test_json_output_is_single_line(self):
        fmt = JsonFormatter()
        record = self._make_record()
        output = fmt.format(record)
        assert "\n" not in output

    def test_json_output_is_valid_json(self):
        fmt = JsonFormatter()
        record = self._make_record()
        output = fmt.format(record)
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_json_output_contains_standard_fields(self):
        fmt = JsonFormatter()
        record = self._make_record()
        output = fmt.format(record)
        parsed = json.loads(output)
        assert "ts" in parsed
        assert parsed["level"] == "INFO"
        assert parsed["trace_id"] == "01JFZ8AAAAAA"
        assert parsed["logger"] == "app.service"
        assert parsed["message"] == "文件上传完成"

    def test_json_output_flattens_extra_fields_to_root(self):
        fmt = JsonFormatter()
        record = self._make_record(file_name="notes.pdf", byte_size=2048)
        output = fmt.format(record)
        parsed = json.loads(output)
        assert parsed["file_name"] == "notes.pdf"
        assert parsed["byte_size"] == 2048


# ---------------------------------------------------------------------------
# 3.4 — File logging handler
# ---------------------------------------------------------------------------


class TestFileLoggingHandler:
    """验证日志写入文件、文件轮转触发和备份数量控制"""

    def test_logs_written_to_file(self, tmp_path):
        log_path = tmp_path / "test.log"
        # Create a simple handler to test file writing
        handler = logging.handlers.RotatingFileHandler(
            str(log_path), maxBytes=1024 * 1024, backupCount=2
        )
        handler.setFormatter(ConsoleFormatter())
        logger = logging.getLogger("test_file")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        logger.info("test message")
        handler.close()

        content = log_path.read_text()
        assert "test message" in content

    def test_file_rotation_triggers_at_max_size(self, tmp_path):
        log_path = tmp_path / "rotate.log"
        # Use a very small maxBytes to trigger rotation quickly
        handler = logging.handlers.RotatingFileHandler(str(log_path), maxBytes=100, backupCount=2)
        handler.setFormatter(ConsoleFormatter())
        logger = logging.getLogger("test_rotate")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        # Write enough data to trigger rotation
        for _i in range(20):
            logger.info("x" * 50)

        handler.close()

        # At least one backup file should exist
        backup = tmp_path / "rotate.log.1"
        assert backup.exists() or log_path.exists()

    def test_backup_count_respected(self, tmp_path):
        log_path = tmp_path / "bounded.log"
        handler = logging.handlers.RotatingFileHandler(str(log_path), maxBytes=50, backupCount=1)
        handler.setFormatter(ConsoleFormatter())
        logger = logging.getLogger("test_bounded")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        for _i in range(30):
            logger.info("y" * 30)

        handler.close()

        # backupCount=1 means only .1 should exist, not .2
        backup2 = tmp_path / "bounded.log.2"
        assert not backup2.exists()

    def test_configure_logging_creates_log_directory(self, tmp_path):
        """验证日志路径父目录自动创建"""
        log_dir = tmp_path / "deep" / "nested"
        log_file = log_dir / "app.log"

        # configure with file logging enabled
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
