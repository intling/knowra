from app.core.config import Settings

DEFAULT_REQUIRED_DOCLING_MODELS = {"layout", "tableformer"}


# 测试模型 bootstrap 默认配置使用独立 DOCUMENT_MODEL_* 命名空间。
# 该测试会在 Settings 尚未声明这些字段时失败，驱动新增配置契约。
def test_document_model_bootstrap_default_settings_are_available() -> None:
    settings = Settings(_env_file=None)

    assert settings.document_model_bootstrap_enabled is True
    assert settings.document_model_bootstrap_strategy == "download_missing"
    assert settings.document_model_bootstrap_failure_policy == "degraded"
    assert settings.document_model_docling_artifact_dir == "storage/document-models/docling"
    assert settings.document_model_hf_endpoint == ""
    assert set(settings.document_model_docling_required_models) == DEFAULT_REQUIRED_DOCLING_MODELS
    assert settings.document_model_tokenizer_name == "Qwen/Qwen2-7B"
    assert settings.document_model_tokenizer_cache_dir == "storage/document-models/tokenizers"


# 测试部署侧可以只通过 DOCUMENT_MODEL_* 覆盖模型准备行为。
# 该测试覆盖下载策略、失败策略、镜像地址、模型目录和 CSV 模型清单解析。
def test_document_model_bootstrap_settings_can_be_overridden(monkeypatch, tmp_path) -> None:
    docling_dir = tmp_path / "docling"
    tokenizer_dir = tmp_path / "tokenizers"
    monkeypatch.setenv("DOCUMENT_MODEL_BOOTSTRAP_ENABLED", "false")
    monkeypatch.setenv("DOCUMENT_MODEL_BOOTSTRAP_STRATEGY", "check_only")
    monkeypatch.setenv("DOCUMENT_MODEL_BOOTSTRAP_FAILURE_POLICY", "fail_fast")
    monkeypatch.setenv("DOCUMENT_MODEL_DOCLING_ARTIFACT_DIR", str(docling_dir))
    monkeypatch.setenv("DOCUMENT_MODEL_HF_ENDPOINT", "https://hf-mirror.example")
    monkeypatch.setenv("DOCUMENT_MODEL_DOCLING_REQUIRED_MODELS", "layout,tableformer,rapidocr")
    monkeypatch.setenv("DOCUMENT_MODEL_TOKENIZER_NAME", "local/qwen-tokenizer")
    monkeypatch.setenv("DOCUMENT_MODEL_TOKENIZER_CACHE_DIR", str(tokenizer_dir))

    settings = Settings(_env_file=None)

    assert settings.document_model_bootstrap_enabled is False
    assert settings.document_model_bootstrap_strategy == "check_only"
    assert settings.document_model_bootstrap_failure_policy == "fail_fast"
    assert settings.document_model_docling_artifact_dir == str(docling_dir)
    assert settings.document_model_hf_endpoint == "https://hf-mirror.example"
    assert set(settings.document_model_docling_required_models) == {
        "layout",
        "tableformer",
        "rapidocr",
    }
    assert settings.document_model_tokenizer_name == "local/qwen-tokenizer"
    assert settings.document_model_tokenizer_cache_dir == str(tokenizer_dir)


# 测试模型 bootstrap 不会从旧解析/分块变量读取 fallback。
# 该测试保护变量层面的隔离和清晰性，避免新流程偷用已有缓存配置。
def test_document_model_bootstrap_settings_do_not_fallback_to_parse_or_chunk_env(
    monkeypatch,
    tmp_path,
) -> None:
    legacy_docling_dir = tmp_path / "legacy-docling-cache"
    legacy_tokenizer = "legacy/tokenizer"
    monkeypatch.setenv("DOCUMENT_PARSE_DOCLING_CACHE_DIR", str(legacy_docling_dir))
    monkeypatch.setenv("DOCUMENT_CHUNK_TOKENIZER_MODEL", legacy_tokenizer)

    settings = Settings(_env_file=None)

    assert settings.document_model_docling_artifact_dir == "storage/document-models/docling"
    assert settings.document_model_docling_artifact_dir != str(legacy_docling_dir)
    assert settings.document_model_tokenizer_name == "Qwen/Qwen2-7B"
    assert settings.document_model_tokenizer_name != legacy_tokenizer
    assert settings.document_model_tokenizer_cache_dir == "storage/document-models/tokenizers"
