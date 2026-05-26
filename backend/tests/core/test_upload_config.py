from app.core.config import Settings

DEFAULT_ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "text/markdown",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


# 测试上传配置具备安全的本地默认值：
# 存储目录、单文件大小限制，以及首批文档/文本 MIME 类型白名单。
def test_upload_settings_default_values() -> None:
    settings = Settings(_env_file=None)

    assert settings.upload_storage_dir == "storage/uploads"
    assert settings.max_upload_bytes == 20 * 1024 * 1024
    assert set(settings.allowed_upload_content_types) == DEFAULT_ALLOWED_CONTENT_TYPES


# 测试部署环境相关的上传配置会从环境变量读取，
# 而不是硬编码在上传服务中。
def test_upload_settings_read_environment_overrides(monkeypatch, tmp_path) -> None:
    storage_dir = tmp_path / "uploaded-files"
    monkeypatch.setenv("UPLOAD_STORAGE_DIR", str(storage_dir))
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "1024")
    monkeypatch.setenv("ALLOWED_UPLOAD_CONTENT_TYPES", "text/plain,application/pdf")

    settings = Settings(_env_file=None)

    assert settings.upload_storage_dir == str(storage_dir)
    assert settings.max_upload_bytes == 1024
    assert set(settings.allowed_upload_content_types) == {"text/plain", "application/pdf"}


# 测试外部 shell 中常见的 DEBUG=release 不会阻断后端配置加载，
# Alembic 会在同一配置入口读取数据库连接串。
def test_settings_treat_release_debug_environment_as_false(monkeypatch) -> None:
    monkeypatch.setenv("DEBUG", "release")

    settings = Settings(_env_file=None)

    assert settings.debug is False
