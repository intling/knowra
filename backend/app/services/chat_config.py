"""Immutable configuration for the chat/LLM API adapter.

All connection parameters, model selection, and operational settings
are captured here so they can be injected into ``ChatAdapter``.
"""

from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings


@dataclass(frozen=True)
class ChatConfig:
    """Immutable configuration for the chat API adapter.

    All connection parameters, model selection, and operational settings
    are captured here so they can be injected into ``ChatAdapter``.
    """

    api_base_url: str
    api_key: str
    model: str
    temperature: float
    max_tokens: int
    request_timeout: float
    max_retries: int

    @classmethod
    def from_settings(cls, settings=None) -> ChatConfig:
        """Build config from the application Settings object.

        When *settings* is ``None`` the cached global settings are used.
        """
        if settings is None:
            settings = get_settings()
        return cls(
            api_base_url=settings.chat_api_base_url,
            api_key=settings.chat_api_key,
            model=settings.chat_model,
            temperature=settings.chat_temperature,
            max_tokens=settings.chat_max_tokens,
            request_timeout=settings.chat_request_timeout,
            max_retries=settings.chat_max_retries,
        )

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict storing the config knobs.

        Used to record the exact settings that produced a chat response.
        Excludes sensitive fields like ``api_key``.
        """
        return {
            "api_base_url": self.api_base_url,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "request_timeout": self.request_timeout,
            "max_retries": self.max_retries,
        }
