from types import SimpleNamespace


def make_ready_bootstrap_readiness():
    return SimpleNamespace(
        status="ready",
        docling=SimpleNamespace(
            component="docling",
            status="ready",
            artifact_dir="storage/document-models/docling",
            missing_models=[],
        ),
        tokenizer=SimpleNamespace(
            component="tokenizer",
            status="ready",
            model_name="Qwen/Qwen2-7B",
            cache_dir="storage/document-models/tokenizers",
            missing_models=[],
        ),
    )


def make_bootstrap_readiness(status: str):
    return SimpleNamespace(
        status=status,
        docling=SimpleNamespace(
            component="docling",
            status=status,
            artifact_dir="storage/document-models/docling",
            missing_models=["layout"] if status == "unavailable" else [],
        ),
        tokenizer=SimpleNamespace(
            component="tokenizer",
            status=status,
            model_name="Qwen/Qwen2-7B",
            cache_dir="storage/document-models/tokenizers",
            missing_models=["Qwen/Qwen2-7B"] if status == "unavailable" else [],
        ),
    )


class FakePreloader:
    def __init__(
        self,
        *,
        converter=None,
        tokenizer=None,
        docling_error: Exception | None = None,
        tokenizer_error: Exception | None = None,
    ) -> None:
        self.converter = converter or object()
        self.tokenizer = tokenizer or object()
        self.docling_error = docling_error
        self.tokenizer_error = tokenizer_error
        self.docling_calls = []
        self.tokenizer_calls = []

    def load_docling_converter(self, *, artifact_dir: str):
        self.docling_calls.append({"artifact_dir": artifact_dir})
        if self.docling_error is not None:
            raise self.docling_error
        return self.converter

    def load_tokenizer(self, *, model_name: str, cache_dir: str):
        self.tokenizer_calls.append({"model_name": model_name, "cache_dir": cache_dir})
        if self.tokenizer_error is not None:
            raise self.tokenizer_error
        return self.tokenizer


# 测试文件 bootstrap ready 后 runtime 先进入 loading，再在预加载成功后进入 ready。
# 该测试驱动进程内模型状态和预加载资源保存，避免请求路径首次加载模型。
def test_document_model_runtime_loads_ready_bootstrap_models_into_memory() -> None:
    from app.services.document_model_runtime import DocumentModelRuntime

    converter = object()
    tokenizer = object()
    preloader = FakePreloader(converter=converter, tokenizer=tokenizer)
    runtime = DocumentModelRuntime.from_bootstrap_readiness(
        make_ready_bootstrap_readiness(),
        preloader=preloader,
    )

    assert runtime.status == "loading"
    assert runtime.docling.status == "loading"
    assert runtime.tokenizer.status == "loading"

    runtime.load_once()

    assert runtime.status == "ready"
    assert runtime.docling.status == "ready"
    assert runtime.docling.resource is converter
    assert runtime.tokenizer.status == "ready"
    assert runtime.tokenizer.resource is tokenizer
    assert preloader.docling_calls == [{"artifact_dir": "storage/document-models/docling"}]
    assert preloader.tokenizer_calls == [
        {"model_name": "Qwen/Qwen2-7B", "cache_dir": "storage/document-models/tokenizers"}
    ]


# 测试预加载失败会把对应组件和聚合状态标记为 unavailable，并保留诊断。
# 该测试保护后台加载失败不会被误报为 ready。
def test_document_model_runtime_marks_preload_failure_unavailable() -> None:
    from app.services.document_model_runtime import DocumentModelRuntime

    runtime = DocumentModelRuntime.from_bootstrap_readiness(
        make_ready_bootstrap_readiness(),
        preloader=FakePreloader(docling_error=RuntimeError("pipeline exploded")),
    )

    runtime.load_once()

    assert runtime.status == "unavailable"
    assert runtime.docling.status == "unavailable"
    assert runtime.docling.missing_models == ["pipeline exploded"]
    assert runtime.tokenizer.status == "ready"


# 测试 bootstrap skipped/unavailable 时不启动内存预加载，保持原状态。
# 该测试确保禁用 bootstrap 时仍可保留旧的懒加载行为。
def test_document_model_runtime_does_not_preload_when_bootstrap_not_ready() -> None:
    from app.services.document_model_runtime import DocumentModelRuntime

    for status in ["skipped", "unavailable"]:
        preloader = FakePreloader()
        runtime = DocumentModelRuntime.from_bootstrap_readiness(
            make_bootstrap_readiness(status),
            preloader=preloader,
        )

        runtime.start_async()
        runtime.load_once()

        assert runtime.status == status
        assert preloader.docling_calls == []
        assert preloader.tokenizer_calls == []
