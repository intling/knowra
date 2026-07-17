# 本文件验证文档向量化配置进入 Settings 的契约。
# 测试覆盖默认运行策略和环境变量覆盖能力，确保不同部署环境能稳定调参。

from app.core.config import Settings


# 默认配置应启用向量化，并固定 API 端点、模型名、维度、编码格式、
# 批次大小、重试次数和超时时间。
# 这个测试防止未配置环境下的向量化行为意外漂移。
def test_document_embedding_default_settings_are_available() -> None:
    settings = Settings(_env_file=None)

    assert settings.document_embedding_enabled is True
    assert settings.document_embedding_api_base_url == "https://router.tumuer.me/v1"
    assert settings.document_embedding_api_key == ""
    assert settings.document_embedding_model == "Qwen/Qwen3-Embedding-0.6B"
    assert settings.document_embedding_dimensions == 1024
    assert settings.document_embedding_encoding_format == "float"
    assert settings.document_embedding_batch_size == 100
    assert settings.document_embedding_max_retries == 3
    assert settings.document_embedding_request_timeout == 60.0


# 环境变量应能覆盖向量化开关、API 端点、密钥、模型、维度、编码格式、
# 批次大小、重试次数和超时时间。
# 这个测试保证部署侧可以不改代码地调整向量化行为。
def test_document_embedding_settings_can_be_overridden_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("DOCUMENT_EMBEDDING_ENABLED", "false")
    monkeypatch.setenv("DOCUMENT_EMBEDDING_API_BASE_URL", "https://custom-api.example.com/v1")
    monkeypatch.setenv("DOCUMENT_EMBEDDING_API_KEY", "sk-test-key-123")
    monkeypatch.setenv("DOCUMENT_EMBEDDING_MODEL", "custom-embedding-model")
    monkeypatch.setenv("DOCUMENT_EMBEDDING_DIMENSIONS", "768")
    monkeypatch.setenv("DOCUMENT_EMBEDDING_ENCODING_FORMAT", "base64")
    monkeypatch.setenv("DOCUMENT_EMBEDDING_BATCH_SIZE", "50")
    monkeypatch.setenv("DOCUMENT_EMBEDDING_MAX_RETRIES", "5")
    monkeypatch.setenv("DOCUMENT_EMBEDDING_REQUEST_TIMEOUT", "30.0")

    settings = Settings(_env_file=None)

    assert settings.document_embedding_enabled is False
    assert settings.document_embedding_api_base_url == "https://custom-api.example.com/v1"
    assert settings.document_embedding_api_key == "sk-test-key-123"
    assert settings.document_embedding_model == "custom-embedding-model"
    assert settings.document_embedding_dimensions == 768
    assert settings.document_embedding_encoding_format == "base64"
    assert settings.document_embedding_batch_size == 50
    assert settings.document_embedding_max_retries == 5
    assert settings.document_embedding_request_timeout == 30.0


# DOCUMENT_EMBEDDING_API_KEY 必须可从 .env 文件读取，不能在代码中硬编码。
# 这个测试用临时 .env 文件验证变量注入路径畅通。
def test_document_embedding_api_key_can_be_read_from_dotenv_file(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DOCUMENT_EMBEDDING_API_KEY=sk-from-dotenv-file\n")

    settings = Settings(_env_file=env_file, _env_file_encoding="utf-8")

    assert settings.document_embedding_api_key == "sk-from-dotenv-file"
