from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings


@dataclass(frozen=True)
class EmbeddingConfig:
    """Immutable configuration for the embedding API adapter.

    All connection parameters, model selection, and operational settings
    are captured here so they can be injected into ``EmbeddingAdapter``.
    """

    api_base_url: str
    api_key: str
    model: str
    dimensions: int
    encoding_format: str
    batch_size: int
    max_retries: int
    request_timeout: float

    @classmethod
    def from_settings(cls, settings=None) -> EmbeddingConfig:
        """Build config from the application Settings object.

        When *settings* is ``None`` the cached global settings are used.
        """
        if settings is None:
            settings = get_settings()
        return cls(
            api_base_url=settings.document_embedding_api_base_url,
            api_key=settings.document_embedding_api_key,
            model=settings.document_embedding_model,
            dimensions=settings.document_embedding_dimensions,
            encoding_format=settings.document_embedding_encoding_format,
            batch_size=settings.document_embedding_batch_size,
            max_retries=settings.document_embedding_max_retries,
            request_timeout=settings.document_embedding_request_timeout,
        )

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict storing the config knobs.

        Used to populate ``DocumentEmbeddingJob.config_json`` so every job
        carries a record of the exact settings that produced its vectors.
        """
        return {
            "api_base_url": self.api_base_url,
            "model": self.model,
            "dimensions": self.dimensions,
            "encoding_format": self.encoding_format,
            "batch_size": self.batch_size,
        }
