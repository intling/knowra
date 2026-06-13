# 本文件验证文档分块配置进入 Settings 的契约。
# 测试覆盖默认运行策略和环境变量覆盖能力，确保不同部署环境能稳定调参。

from app.core.config import Settings


# 默认配置应启用自动分块，并固定 tokenizer、token 上限、结构化分块策略和存储参数。
# 这个测试防止未配置环境下的分块行为意外漂移。
def test_document_chunking_default_settings_are_available() -> None:
    settings = Settings(_env_file=None)

    assert settings.document_chunking_enabled is True
    assert settings.document_chunk_max_tokens == 512
    assert settings.document_chunk_tokenizer_model == "Qwen/Qwen2-7B"
    assert settings.document_chunk_merge_peers is True
    assert settings.document_chunk_repeat_table_header is True
    assert settings.document_chunk_inline_text_max_bytes == 2048
    assert settings.document_chunk_artifact_storage_dir == "storage/chunks"


# 环境变量应能覆盖自动分块开关、tokenizer、token 上限、结构化策略和存储目录。
# 这个测试保证部署侧可以不改代码地调整分块行为。
def test_document_chunking_settings_can_be_overridden_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("DOCUMENT_CHUNKING_ENABLED", "false")
    monkeypatch.setenv("DOCUMENT_CHUNK_MAX_TOKENS", "256")
    monkeypatch.setenv("DOCUMENT_CHUNK_TOKENIZER_MODEL", "local/qwen-tokenizer")
    monkeypatch.setenv("DOCUMENT_CHUNK_MERGE_PEERS", "false")
    monkeypatch.setenv("DOCUMENT_CHUNK_REPEAT_TABLE_HEADER", "false")
    monkeypatch.setenv("DOCUMENT_CHUNK_INLINE_TEXT_MAX_BYTES", "1024")
    monkeypatch.setenv("DOCUMENT_CHUNK_ARTIFACT_STORAGE_DIR", "tmp/chunks")

    settings = Settings(_env_file=None)

    assert settings.document_chunking_enabled is False
    assert settings.document_chunk_max_tokens == 256
    assert settings.document_chunk_tokenizer_model == "local/qwen-tokenizer"
    assert settings.document_chunk_merge_peers is False
    assert settings.document_chunk_repeat_table_header is False
    assert settings.document_chunk_inline_text_max_bytes == 1024
    assert settings.document_chunk_artifact_storage_dir == "tmp/chunks"
