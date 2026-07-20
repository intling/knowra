import signal
from importlib import import_module
from types import SimpleNamespace

import pytest


def get_bootstrap_module():
    try:
        return import_module("app.services.document_model_bootstrap")
    except ModuleNotFoundError as exc:
        raise AssertionError("缺少 app.services.document_model_bootstrap 模块") from exc


def make_settings(
    *,
    enabled: bool = True,
    strategy: str = "check_only",
    failure_policy: str = "degraded",
    hf_endpoint: str = "",
):
    return SimpleNamespace(
        document_model_bootstrap_enabled=enabled,
        document_model_bootstrap_strategy=strategy,
        document_model_bootstrap_failure_policy=failure_policy,
        document_model_docling_artifact_dir="storage/document-models/docling",
        document_model_hf_endpoint=hf_endpoint,
        document_model_docling_required_models=["layout", "tableformer"],
        document_model_tokenizer_name="Qwen/Qwen2-7B",
        document_model_tokenizer_cache_dir="storage/document-models/tokenizers",
    )


class FakeModelAdapter:
    def __init__(
        self,
        *,
        name: str,
        available: bool,
        missing_models: list[str] | None = None,
        available_after_download: bool = False,
        environ: dict[str, str] | None = None,
        expected_endpoint: str | None = None,
    ) -> None:
        self.name = name
        self.available = available
        self.missing_models = missing_models or []
        self.available_after_download = available_after_download
        self.environ = environ
        self.expected_endpoint = expected_endpoint
        self.check_calls = []
        self.download_calls = []

    def check(self, **kwargs):
        if self.expected_endpoint is not None:
            assert self.environ is not None
            assert self.environ.get("HF_ENDPOINT") == self.expected_endpoint
        self.check_calls.append(kwargs)
        status = "ready" if self.available else "unavailable"
        return SimpleNamespace(
            component=self.name,
            status=status,
            missing_models=[] if self.available else list(self.missing_models),
        )

    def download(self, **kwargs) -> None:
        self.download_calls.append(kwargs)
        if self.available_after_download:
            self.available = True
            self.missing_models = []


class InterruptingDownloadAdapter(FakeModelAdapter):
    def download(self, **kwargs) -> None:
        self.download_calls.append(kwargs)
        handler = signal.getsignal(signal.SIGINT)
        assert callable(handler)
        handler(signal.SIGINT, None)
        self.available = True
        self.missing_models = []


# 测试禁用 bootstrap 时不会检查或下载模型。
# 该测试驱动 skipped 状态，并保护禁用时不触发外部依赖访问。
def test_document_model_bootstrap_skips_when_disabled() -> None:
    module = get_bootstrap_module()
    docling = FakeModelAdapter(name="docling", available=False, missing_models=["layout"])
    tokenizer = FakeModelAdapter(
        name="tokenizer",
        available=False,
        missing_models=["Qwen/Qwen2-7B"],
    )
    service = module.DocumentModelBootstrapService(
        settings=make_settings(enabled=False),
        docling_adapter=docling,
        tokenizer_adapter=tokenizer,
        environ={},
    )

    result = service.run()

    assert result.status == "skipped"
    assert result.docling.status == "skipped"
    assert result.tokenizer.status == "skipped"
    assert docling.check_calls == []
    assert tokenizer.check_calls == []
    assert docling.download_calls == []
    assert tokenizer.download_calls == []


# 测试 check_only 发现缺失模型时只报告 unavailable，不下载。
# 该测试覆盖缺失 Docling artifacts 和 tokenizer 的诊断输出。
def test_document_model_bootstrap_check_only_reports_missing_without_download() -> None:
    module = get_bootstrap_module()
    docling = FakeModelAdapter(name="docling", available=False, missing_models=["layout"])
    tokenizer = FakeModelAdapter(
        name="tokenizer",
        available=False,
        missing_models=["Qwen/Qwen2-7B"],
    )
    service = module.DocumentModelBootstrapService(
        settings=make_settings(strategy="check_only"),
        docling_adapter=docling,
        tokenizer_adapter=tokenizer,
        environ={},
    )

    result = service.run()

    assert result.status == "unavailable"
    assert result.docling.status == "unavailable"
    assert result.docling.missing_models == ["layout"]
    assert result.tokenizer.status == "unavailable"
    assert result.tokenizer.missing_models == ["Qwen/Qwen2-7B"]
    assert docling.download_calls == []
    assert tokenizer.download_calls == []


# 测试 download_missing 会下载缺失模型并重新检查到 ready。
# 该测试驱动启动流程先检查、下载，再以最终 readiness 为准。
def test_document_model_bootstrap_download_missing_rechecks_and_becomes_ready() -> None:
    module = get_bootstrap_module()
    docling = FakeModelAdapter(
        name="docling",
        available=False,
        missing_models=["layout"],
        available_after_download=True,
    )
    tokenizer = FakeModelAdapter(
        name="tokenizer",
        available=False,
        missing_models=["Qwen/Qwen2-7B"],
        available_after_download=True,
    )
    service = module.DocumentModelBootstrapService(
        settings=make_settings(strategy="download_missing"),
        docling_adapter=docling,
        tokenizer_adapter=tokenizer,
        environ={},
    )

    result = service.run()

    assert result.status == "ready"
    assert result.docling.status == "ready"
    assert result.tokenizer.status == "ready"
    assert len(docling.check_calls) == 2
    assert len(tokenizer.check_calls) == 2
    assert len(docling.download_calls) == 1
    assert len(tokenizer.download_calls) == 1


# 测试 Docling adapter 能识别真实下载后的 tableformer 嵌套 artifacts 目录。
# 该测试保护启动检查不会在下载成功后继续误报 tableformer 缺失。
def test_docling_model_adapter_recognizes_nested_tableformer_artifacts(tmp_path) -> None:
    module = get_bootstrap_module()
    artifact_dir = tmp_path / "document-models" / "docling"
    artifact_dir.joinpath("docling-project--docling-layout-heron").mkdir(parents=True)
    artifact_dir.joinpath(
        "docling-project--docling-models",
        "model_artifacts",
        "tableformer",
    ).mkdir(parents=True)

    result = module.DoclingModelAdapter().check(
        artifact_dir=str(artifact_dir),
        required_models=["layout", "tableformer"],
    )

    assert result.status == "ready"
    assert result.missing_models == []


# 测试 Docling adapter 检测到 .incomplete 文件时将模型标记为缺失。
# 该测试保护 HuggingFace Hub 下载中断后不会误判模型已就绪。
def test_docling_model_adapter_detects_incomplete_download(tmp_path) -> None:
    module = get_bootstrap_module()
    artifact_dir = tmp_path / "document-models" / "docling"
    layout_dir = artifact_dir / "docling-project--docling-layout-heron"
    layout_dir.mkdir(parents=True)
    # Simulate an interrupted HuggingFace Hub download that left an
    # .incomplete marker behind – the directory exists but the weights
    # are missing.
    incomplete_marker = layout_dir / ".cache" / "huggingface" / "download" / "abc123.incomplete"
    incomplete_marker.parent.mkdir(parents=True)
    incomplete_marker.write_text("")

    result = module.DoclingModelAdapter().check(
        artifact_dir=str(artifact_dir),
        required_models=["layout", "tableformer"],
    )

    assert result.status == "unavailable"
    assert "layout" in result.missing_models


# 测试 fail_fast 在模型不可用时中止启动。
# 该测试要求实现提供项目内异常，避免应用在必需模型缺失时继续服务。
def test_document_model_bootstrap_fail_fast_raises_when_unavailable() -> None:
    module = get_bootstrap_module()
    docling = FakeModelAdapter(name="docling", available=False, missing_models=["layout"])
    tokenizer = FakeModelAdapter(name="tokenizer", available=True)
    service = module.DocumentModelBootstrapService(
        settings=make_settings(strategy="check_only", failure_policy="fail_fast"),
        docling_adapter=docling,
        tokenizer_adapter=tokenizer,
        environ={},
    )

    with pytest.raises(module.DocumentModelBootstrapError, match="layout"):
        service.run()


# 测试 degraded 在模型不可用时保留状态并允许应用继续。
# 该测试驱动降级启动语义，后续解析/分块通过 readiness 快速失败。
def test_document_model_bootstrap_degraded_returns_unavailable_result() -> None:
    module = get_bootstrap_module()
    docling = FakeModelAdapter(name="docling", available=False, missing_models=["layout"])
    tokenizer = FakeModelAdapter(name="tokenizer", available=True)
    service = module.DocumentModelBootstrapService(
        settings=make_settings(strategy="check_only", failure_policy="degraded"),
        docling_adapter=docling,
        tokenizer_adapter=tokenizer,
        environ={},
    )

    result = service.run()

    assert result.status == "unavailable"
    assert result.docling.missing_models == ["layout"]
    assert result.tokenizer.status == "ready"


# 测试 HF endpoint 会在任何 Hugging Face/Docling 检查前写入环境。
# 该测试保护镜像地址配置顺序，并避免代码硬编码镜像。
def test_document_model_bootstrap_applies_hf_endpoint_before_model_checks() -> None:
    module = get_bootstrap_module()
    environ = {}
    endpoint = "https://hf-mirror.example"
    docling = FakeModelAdapter(
        name="docling",
        available=True,
        environ=environ,
        expected_endpoint=endpoint,
    )
    tokenizer = FakeModelAdapter(
        name="tokenizer",
        available=True,
        environ=environ,
        expected_endpoint=endpoint,
    )
    service = module.DocumentModelBootstrapService(
        settings=make_settings(hf_endpoint=endpoint),
        docling_adapter=docling,
        tokenizer_adapter=tokenizer,
        environ=environ,
    )

    result = service.run()

    assert result.status == "ready"
    assert environ["HF_ENDPOINT"] == endpoint


# 测试下载过程中 Ctrl+C 能够中断同步阻塞的模型 bootstrap。
# uvicorn 的 signal handler 只标记退出请求，不会直接抛 KeyboardInterrupt；
# bootstrap 需要在下载窗口内恢复可中断语义，并在退出后还原原 handler。
def test_document_model_bootstrap_download_translates_sigint_to_keyboard_interrupt() -> None:
    module = get_bootstrap_module()
    signal_calls = []

    def uvicorn_like_handler(signum, frame) -> None:
        signal_calls.append(signum)

    original_handler = signal.signal(signal.SIGINT, uvicorn_like_handler)
    try:
        docling = InterruptingDownloadAdapter(
            name="docling",
            available=False,
            missing_models=["layout"],
        )
        tokenizer = FakeModelAdapter(name="tokenizer", available=True)
        service = module.DocumentModelBootstrapService(
            settings=make_settings(strategy="download_missing"),
            docling_adapter=docling,
            tokenizer_adapter=tokenizer,
            environ={},
        )

        with pytest.raises(KeyboardInterrupt):
            service.run()

        assert signal_calls == []
        assert signal.getsignal(signal.SIGINT) is uvicorn_like_handler
    finally:
        signal.signal(signal.SIGINT, original_handler)
