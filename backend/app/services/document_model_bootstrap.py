from __future__ import annotations

import os
import signal
from collections.abc import MutableMapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


class DocumentModelBootstrapError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelComponentReadiness:
    component: str
    status: str
    missing_models: list[str] = field(default_factory=list)
    artifact_dir: str | None = None
    model_name: str | None = None
    cache_dir: str | None = None


@dataclass(frozen=True)
class DocumentModelReadiness:
    status: str
    docling: ModelComponentReadiness
    tokenizer: ModelComponentReadiness


def skipped_readiness() -> DocumentModelReadiness:
    return DocumentModelReadiness(
        status="skipped",
        docling=ModelComponentReadiness(component="docling", status="skipped"),
        tokenizer=ModelComponentReadiness(component="tokenizer", status="skipped"),
    )


class DocumentModelBootstrapService:
    def __init__(
        self,
        *,
        settings: Any,
        docling_adapter: object | None = None,
        tokenizer_adapter: object | None = None,
        environ: MutableMapping[str, str] | None = None,
    ) -> None:
        self.settings = settings
        self.environ = environ if environ is not None else os.environ
        self.docling_adapter = docling_adapter or DoclingModelAdapter()
        self.tokenizer_adapter = tokenizer_adapter or TokenizerModelAdapter()

    def run(self) -> DocumentModelReadiness:
        if not self.settings.document_model_bootstrap_enabled:
            result = skipped_readiness()
            self._log_result(result)
            return result

        self._configure_hf_endpoint()
        docling = self._prepare_docling()
        tokenizer = self._prepare_tokenizer()
        status = (
            "ready" if docling.status == "ready" and tokenizer.status == "ready" else "unavailable"
        )
        result = DocumentModelReadiness(status=status, docling=docling, tokenizer=tokenizer)
        self._log_result(result)

        if (
            status != "ready"
            and self.settings.document_model_bootstrap_failure_policy == "fail_fast"
        ):
            missing = [*docling.missing_models, *tokenizer.missing_models]
            raise DocumentModelBootstrapError(
                f"Document models are unavailable: {', '.join(missing) or status}"
            )

        return result

    def _configure_hf_endpoint(self) -> None:
        endpoint = self.settings.document_model_hf_endpoint
        if endpoint:
            self.environ["HF_ENDPOINT"] = endpoint

    def _prepare_docling(self) -> ModelComponentReadiness:
        first = self._coerce_component(
            self.docling_adapter.check(
                artifact_dir=self.settings.document_model_docling_artifact_dir,
                required_models=self.settings.document_model_docling_required_models,
            ),
            component="docling",
            artifact_dir=self.settings.document_model_docling_artifact_dir,
        )
        if (
            first.status == "ready"
            or self.settings.document_model_bootstrap_strategy != "download_missing"
        ):
            return first

        with interruptible_download():
            self.docling_adapter.download(
                artifact_dir=self.settings.document_model_docling_artifact_dir,
                required_models=first.missing_models
                or self.settings.document_model_docling_required_models,
            )
        return self._coerce_component(
            self.docling_adapter.check(
                artifact_dir=self.settings.document_model_docling_artifact_dir,
                required_models=self.settings.document_model_docling_required_models,
            ),
            component="docling",
            artifact_dir=self.settings.document_model_docling_artifact_dir,
        )

    def _prepare_tokenizer(self) -> ModelComponentReadiness:
        first = self._coerce_component(
            self.tokenizer_adapter.check(
                model_name=self.settings.document_model_tokenizer_name,
                cache_dir=self.settings.document_model_tokenizer_cache_dir,
            ),
            component="tokenizer",
            model_name=self.settings.document_model_tokenizer_name,
            cache_dir=self.settings.document_model_tokenizer_cache_dir,
        )
        if (
            first.status == "ready"
            or self.settings.document_model_bootstrap_strategy != "download_missing"
        ):
            return first

        with interruptible_download():
            self.tokenizer_adapter.download(
                model_name=self.settings.document_model_tokenizer_name,
                cache_dir=self.settings.document_model_tokenizer_cache_dir,
            )
        return self._coerce_component(
            self.tokenizer_adapter.check(
                model_name=self.settings.document_model_tokenizer_name,
                cache_dir=self.settings.document_model_tokenizer_cache_dir,
            ),
            component="tokenizer",
            model_name=self.settings.document_model_tokenizer_name,
            cache_dir=self.settings.document_model_tokenizer_cache_dir,
        )

    def _coerce_component(
        self,
        value: object,
        *,
        component: str,
        artifact_dir: str | None = None,
        model_name: str | None = None,
        cache_dir: str | None = None,
    ) -> ModelComponentReadiness:
        return ModelComponentReadiness(
            component=str(getattr(value, "component", component)),
            status=str(value.status),
            missing_models=list(getattr(value, "missing_models", []) or []),
            artifact_dir=getattr(value, "artifact_dir", artifact_dir),
            model_name=getattr(value, "model_name", model_name),
            cache_dir=getattr(value, "cache_dir", cache_dir),
        )

    def _log_result(self, result: DocumentModelReadiness) -> None:
        if result.status == "ready":
            logger.info(
                "Document model bootstrap ready",
                status=result.status,
                strategy=self.settings.document_model_bootstrap_strategy,
                failure_policy=self.settings.document_model_bootstrap_failure_policy,
                docling_artifact_dir=result.docling.artifact_dir,
                tokenizer_cache_dir=result.tokenizer.cache_dir,
            )
        elif result.status == "skipped":
            logger.info("Document model bootstrap skipped", status=result.status)
        else:
            logger.warning(
                "Document model bootstrap unavailable",
                status=result.status,
                missing_models=[
                    *result.docling.missing_models,
                    *result.tokenizer.missing_models,
                ],
            )


@contextmanager
def interruptible_download():
    previous_handler = signal.getsignal(signal.SIGINT)

    def raise_keyboard_interrupt(signum, frame) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, raise_keyboard_interrupt)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous_handler)


class DoclingModelAdapter:
    _MODEL_PATHS = {
        "layout": ("docling-project--docling-layout-heron",),
        "tableformer": ("docling-project--docling-models/model_artifacts/tableformer",),
    }

    def check(
        self,
        *,
        artifact_dir: str,
        required_models: list[str],
    ) -> ModelComponentReadiness:
        root = Path(artifact_dir)
        missing = [model for model in required_models if not self._has_model(root, model)]
        return ModelComponentReadiness(
            component="docling",
            status="ready" if not missing else "unavailable",
            missing_models=missing,
            artifact_dir=artifact_dir,
        )

    def download(self, *, artifact_dir: str, required_models: list[str]) -> None:
        from docling.utils.model_downloader import download_models

        selected = set(required_models)
        download_models(
            output_dir=Path(artifact_dir),
            with_layout="layout" in selected,
            with_tableformer="tableformer" in selected,
            with_tableformer_v2=False,
            with_code_formula=False,
            with_picture_classifier=False,
            with_rapidocr=False,
            with_easyocr=False,
            progress=False,
        )

    def _has_model(self, root: Path, model: str) -> bool:
        paths = self._MODEL_PATHS.get(model)
        if paths is None:
            return self._path_has_complete_model(root.joinpath(model))
        return all(
            self._path_has_complete_model(root.joinpath(path)) for path in paths
        )

    @staticmethod
    def _path_has_complete_model(target: Path) -> bool:
        """Return True if *target* exists and contains no incomplete-download markers."""
        if not target.exists():
            return False
        # HuggingFace Hub / snapshot_download leaves *.incomplete files when a
        # download is interrupted – treat those as missing so the bootstrap
        # re-downloads rather than failing at pipeline-initialisation time.
        if any(target.rglob("*.incomplete")):
            return False
        return True


class TokenizerModelAdapter:
    def check(self, *, model_name: str, cache_dir: str) -> ModelComponentReadiness:
        try:
            from transformers import AutoTokenizer

            AutoTokenizer.from_pretrained(
                model_name,
                cache_dir=cache_dir,
                local_files_only=True,
            )
        except Exception:
            return ModelComponentReadiness(
                component="tokenizer",
                status="unavailable",
                missing_models=[model_name],
                model_name=model_name,
                cache_dir=cache_dir,
            )

        return ModelComponentReadiness(
            component="tokenizer",
            status="ready",
            model_name=model_name,
            cache_dir=cache_dir,
        )

    def download(self, *, model_name: str, cache_dir: str) -> None:
        from transformers import AutoTokenizer

        AutoTokenizer.from_pretrained(
            model_name,
            cache_dir=cache_dir,
            local_files_only=False,
        )
