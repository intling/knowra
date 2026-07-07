from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.document_chunker import make_huggingface_tokenizer
from app.services.document_model_bootstrap import DocumentModelReadiness
from app.services.document_parser import DoclingParserAdapter

logger = get_logger(__name__)


@dataclass
class RuntimeModelComponent:
    component: str
    status: str
    missing_models: list[str] = field(default_factory=list)
    artifact_dir: str | None = None
    model_name: str | None = None
    cache_dir: str | None = None
    resource: Any | None = None


@dataclass
class DocumentModelRuntime:
    docling: RuntimeModelComponent
    tokenizer: RuntimeModelComponent
    preloader: object
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _is_shutting_down: bool = field(default=False, init=False, repr=False)

    @classmethod
    def from_bootstrap_readiness(
        cls,
        readiness: DocumentModelReadiness,
        *,
        preloader: object | None = None,
    ) -> DocumentModelRuntime:
        return cls(
            docling=runtime_component_from_bootstrap(getattr(readiness, "docling", None)),
            tokenizer=runtime_component_from_bootstrap(getattr(readiness, "tokenizer", None)),
            preloader=preloader or DocumentModelPreloader(),
        )

    @property
    def status(self) -> str:
        if self._is_shutting_down:
            return "shutting_down"
        statuses = {self.docling.status, self.tokenizer.status}
        if "shutting_down" in statuses:
            return "shutting_down"
        if "unavailable" in statuses:
            return "unavailable"
        if "loading" in statuses:
            return "loading"
        if statuses == {"skipped"}:
            return "skipped"
        if statuses == {"ready"}:
            return "ready"
        if "ready" in statuses and "skipped" in statuses:
            return "ready"
        return "unavailable"

    def start_async(self) -> None:
        if self._is_shutting_down:
            return
        if not self._has_loading_components():
            logger.info("Document model runtime preload skipped", status=self.status)
            return
        if self._thread is not None:
            return

        self._thread = threading.Thread(
            target=self.load_once,
            name="document-model-preload",
            daemon=True,
        )
        self._thread.start()

    def shutdown(self, *, timeout_seconds: float = 0) -> None:
        with self._lock:
            already_shutting_down = self._is_shutting_down
            self._is_shutting_down = True
            for component in (self.docling, self.tokenizer):
                component.status = "shutting_down"

        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout_seconds)
            if thread.is_alive():
                logger.warning(
                    "Document model runtime preload thread did not stop before timeout",
                    timeout_seconds=timeout_seconds,
                )

        if already_shutting_down:
            return

        released_count = 0
        for component in (self.docling, self.tokenizer):
            resource = component.resource
            if resource is None:
                continue
            self._cleanup_resource(component=component.component, resource=resource)
            component.resource = None
            released_count += 1

        self._cleanup_torch_cuda_cache()
        logger.info("Document model runtime shutdown completed", released_count=released_count)

    def load_once(self) -> None:
        if self._is_shutting_down:
            return
        if not self._has_loading_components():
            return

        logger.info("Document model runtime preload started", status=self.status)
        if self.docling.status == "loading":
            try:
                resource = self.preloader.load_docling_converter(
                    artifact_dir=str(self.docling.artifact_dir)
                )
            except Exception as exc:
                self._mark_component_unavailable(self.docling, str(exc))
                logger.error(
                    "Document model runtime docling preload failed",
                    error=str(exc),
                    exc_info=True,
                )
            else:
                self._mark_component_ready(self.docling, resource)
                logger.info("Document model runtime docling preload ready")

        if self._is_shutting_down:
            return
        if self.tokenizer.status == "loading":
            try:
                resource = self.preloader.load_tokenizer(
                    model_name=str(self.tokenizer.model_name),
                    cache_dir=str(self.tokenizer.cache_dir),
                )
            except Exception as exc:
                self._mark_component_unavailable(self.tokenizer, str(exc))
                logger.error(
                    "Document model runtime tokenizer preload failed",
                    error=str(exc),
                    exc_info=True,
                )
            else:
                self._mark_component_ready(self.tokenizer, resource)
                logger.info("Document model runtime tokenizer preload ready")

    def _has_loading_components(self) -> bool:
        if self._is_shutting_down:
            return False
        return self.docling.status == "loading" or self.tokenizer.status == "loading"

    def _mark_component_ready(self, component: RuntimeModelComponent, resource: object) -> None:
        with self._lock:
            if self._is_shutting_down:
                return
            component.status = "ready"
            component.missing_models = []
            component.resource = resource

    def _mark_component_unavailable(self, component: RuntimeModelComponent, message: str) -> None:
        with self._lock:
            if self._is_shutting_down:
                return
            component.status = "unavailable"
            component.missing_models = [message] if message else []
            component.resource = None

    def _cleanup_resource(self, *, component: str, resource: object) -> None:
        for method_name in ("close", "shutdown", "dispose", "release"):
            method = getattr(resource, method_name, None)
            if not callable(method):
                continue
            try:
                method()
            except Exception as exc:
                logger.error(
                    "Document model runtime resource cleanup failed",
                    component=component,
                    method=method_name,
                    error=str(exc),
                    exc_info=True,
                )

    def _cleanup_torch_cuda_cache(self) -> None:
        torch_module = sys.modules.get("torch")
        if torch_module is None:
            return
        cuda = getattr(torch_module, "cuda", None)
        is_available: Callable[[], bool] | None = getattr(cuda, "is_available", None)
        empty_cache = getattr(cuda, "empty_cache", None)
        if not callable(is_available) or not callable(empty_cache):
            return
        try:
            if is_available():
                empty_cache()
        except Exception as exc:
            logger.error(
                "Document model runtime torch cuda cleanup failed",
                error=str(exc),
                exc_info=True,
            )


class DocumentModelPreloader:
    def __init__(self, *, settings: object | None = None) -> None:
        self.settings = settings or get_settings()

    def load_docling_converter(self, *, artifact_dir: str) -> object:
        adapter = DoclingParserAdapter(
            ocr_enabled=self.settings.document_parse_ocr_enabled,
            max_pages=self.settings.document_parse_max_pages,
            docling_artifact_dir=artifact_dir,
        )
        return adapter.create_preloaded_converter()

    def load_tokenizer(self, *, model_name: str, cache_dir: str) -> object:
        return make_huggingface_tokenizer(
            model_name=model_name,
            max_tokens=self.settings.document_chunk_max_tokens,
            cache_dir=cache_dir,
        )


def runtime_component_from_bootstrap(component: object | None) -> RuntimeModelComponent:
    if component is None:
        return RuntimeModelComponent(component="unknown", status="skipped")

    status = str(getattr(component, "status", "skipped"))
    runtime_status = "loading" if status == "ready" else status
    return RuntimeModelComponent(
        component=str(getattr(component, "component", "unknown")),
        status=runtime_status,
        missing_models=list(getattr(component, "missing_models", []) or []),
        artifact_dir=getattr(component, "artifact_dir", None),
        model_name=getattr(component, "model_name", None),
        cache_dir=getattr(component, "cache_dir", None),
    )
