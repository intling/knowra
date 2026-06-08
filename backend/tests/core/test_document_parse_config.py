from app.core.config import Settings

DEFAULT_DOCUMENT_PARSE_CONTENT_TYPES = {
    "application/pdf",
    "text/markdown",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

DEFAULT_DOCUMENT_PARSE_EXTENSIONS = {".docx", ".md", ".markdown", ".pdf", ".pptx", ".txt"}


# 测试上传白名单和解析格式策略的默认值一致性：
# 默认上传允许列表已包含解析目标格式，部署可以按需收窄。
def test_document_parse_allowed_formats_default_includes_upload_defaults() -> None:
    settings = Settings(_env_file=None)

    assert "application/vnd.openxmlformats-officedocument.presentationml.presentation" in set(
        settings.allowed_upload_content_types
    )
    assert (
        set(settings.document_parse_allowed_content_types) == DEFAULT_DOCUMENT_PARSE_CONTENT_TYPES
    )
    assert set(settings.document_parse_allowed_extensions) == DEFAULT_DOCUMENT_PARSE_EXTENSIONS


# 测试解析配置默认值覆盖首版资源边界和调度策略。
def test_document_parse_settings_default_values() -> None:
    settings = Settings(_env_file=None)

    assert settings.document_parse_enabled is True
    assert settings.document_parse_artifact_dir == "storage/parsed"
    assert settings.document_parse_max_bytes == 50 * 1024 * 1024
    assert settings.document_parse_max_pages == 100
    assert settings.document_parse_ocr_enabled is False
    assert settings.document_parse_docling_cache_dir == "storage/docling-cache"
    assert settings.document_parse_dispatcher == "background_tasks"


# 测试部署可以独立覆盖解析允许 MIME、扩展名和资源限制，
# 且不会改写上传配置。
def test_document_parse_settings_read_environment_overrides(monkeypatch, tmp_path) -> None:
    artifact_dir = tmp_path / "parsed"
    cache_dir = tmp_path / "docling-cache"
    monkeypatch.setenv("DOCUMENT_PARSE_ENABLED", "false")
    monkeypatch.setenv("DOCUMENT_PARSE_ARTIFACT_DIR", str(artifact_dir))
    monkeypatch.setenv("DOCUMENT_PARSE_MAX_BYTES", "2048")
    monkeypatch.setenv("DOCUMENT_PARSE_MAX_PAGES", "3")
    monkeypatch.setenv("DOCUMENT_PARSE_OCR_ENABLED", "true")
    monkeypatch.setenv("DOCUMENT_PARSE_DOCLING_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("DOCUMENT_PARSE_DISPATCHER", "queue")
    monkeypatch.setenv("DOCUMENT_PARSE_ALLOWED_CONTENT_TYPES", "text/plain,text/markdown")
    monkeypatch.setenv("DOCUMENT_PARSE_ALLOWED_EXTENSIONS", ".txt,.md")

    settings = Settings(_env_file=None)

    assert settings.document_parse_enabled is False
    assert settings.document_parse_artifact_dir == str(artifact_dir)
    assert settings.document_parse_max_bytes == 2048
    assert settings.document_parse_max_pages == 3
    assert settings.document_parse_ocr_enabled is True
    assert settings.document_parse_docling_cache_dir == str(cache_dir)
    assert settings.document_parse_dispatcher == "queue"
    assert set(settings.document_parse_allowed_content_types) == {"text/plain", "text/markdown"}
    assert set(settings.document_parse_allowed_extensions) == {".txt", ".md"}
    assert "application/pdf" in set(settings.allowed_upload_content_types)
