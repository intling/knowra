"""Tests for logging-related configuration in app.core.config.Settings."""

from app.core.config import Settings


class TestLoggingConfigDefaults:
    """2.1 验证新增日志配置项的默认值"""

    def test_log_level_default(self):
        settings = Settings(_env_file=None)
        assert settings.log_level == "INFO"

    def test_log_format_default_when_debug_true(self):
        """debug=true（默认）且未设置 LOG_FORMAT 时，自动推断为 console"""
        settings = Settings(_env_file=None)
        assert settings.debug is True
        assert settings.log_format == "console"

    def test_log_format_default_when_debug_false(self, monkeypatch):
        """debug=false 且未设置 LOG_FORMAT 时，自动推断为 json"""
        monkeypatch.setenv("DEBUG", "false")
        settings = Settings(_env_file=None)
        assert settings.debug is False
        assert settings.log_format == "json"

    def test_log_file_path_default(self):
        settings = Settings(_env_file=None)
        assert settings.log_file_path == "logs/knowra.log"

    def test_log_file_max_size_default(self):
        settings = Settings(_env_file=None)
        assert settings.log_file_max_size == 10 * 1024 * 1024  # 10 MB

    def test_log_file_backup_count_default(self):
        settings = Settings(_env_file=None)
        assert settings.log_file_backup_count == 5


class TestLoggingConfigFromEnvironment:
    """2.1 验证日志配置项可从环境变量读取"""

    def test_log_level_from_env(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        settings = Settings(_env_file=None)
        assert settings.log_level == "DEBUG"

    def test_log_format_explicit_overrides_debug_heuristic(self, monkeypatch):
        """显式设置 LOG_FORMAT 时优先于 debug 的自动推断"""
        monkeypatch.setenv("LOG_FORMAT", "json")
        monkeypatch.setenv("DEBUG", "true")
        settings = Settings(_env_file=None)
        assert settings.debug is True
        assert settings.log_format == "json"

    def test_log_file_path_from_env(self, monkeypatch):
        monkeypatch.setenv("LOG_FILE_PATH", "logs/app.log")
        settings = Settings(_env_file=None)
        assert settings.log_file_path == "logs/app.log"

    def test_log_file_max_size_from_env(self, monkeypatch):
        monkeypatch.setenv("LOG_FILE_MAX_SIZE", "5242880")
        settings = Settings(_env_file=None)
        assert settings.log_file_max_size == 5_242_880

    def test_log_file_backup_count_from_env(self, monkeypatch):
        monkeypatch.setenv("LOG_FILE_BACKUP_COUNT", "3")
        settings = Settings(_env_file=None)
        assert settings.log_file_backup_count == 3
