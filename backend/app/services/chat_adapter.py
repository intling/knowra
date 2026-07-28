"""Encapsulates an OpenAI-compatible chat completion endpoint.

Provides a thin adapter over ``POST /v1/chat/completions`` with retry,
error handling, and structured return types — following the same patterns
as ``EmbeddingAdapter`` but for the chat domain.
"""

import random
import time
from dataclasses import dataclass

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from app.core.logging import get_logger
from app.services.chat_config import ChatConfig


class ChatError(Exception):
    """Base exception for all chat operations."""

    pass


class ChatAPIError(ChatError):
    """Raised when the chat API call fails after all retries are exhausted."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ChatResult:
    """A single chat completion result produced by the API.

    Attributes:
        content: The generated text response from the model.
        model: The model used to produce this completion.
        prompt_tokens: Number of tokens in the prompt.
        completion_tokens: Number of tokens in the generated completion.
        total_tokens: Total tokens consumed (prompt + completion).
    """

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatAdapter:
    """Encapsulates an OpenAI-compatible ``POST /v1/chat/completions`` endpoint.

    The adapter handles retry with exponential backoff and error wrapping.
    No third-party SDK types are exposed to callers — every return value
    is a project-internal dataclass.
    """

    def __init__(
        self,
        *,
        config: ChatConfig,
        client: object | None = None,
    ) -> None:
        self.config = config
        if client is not None:
            self._client = client
        else:
            if not config.api_key:
                raise ChatAPIError(
                    "Chat API key is not configured. "
                    "Set CHAT_API_KEY in your .env file."
                )
            self._client = OpenAI(
                base_url=config.api_base_url,
                api_key=config.api_key,
                timeout=config.request_timeout,
            )
        self._logger = get_logger(__name__)

    # ── public API ──────────────────────────────────────────────────

    def generate(self, messages: list[dict], *, stream: bool = False) -> ChatResult:
        """Generate a chat completion for *messages*.

        Args:
            messages: A list of message dicts, each with ``role`` and ``content``.
            stream: Reserved for Phase 2. When ``True``, raises ``NotImplementedError``.

        Returns:
            ChatResult with the generated content and token usage stats.

        Raises:
            NotImplementedError: If ``stream=True`` (reserved for Phase 2).
            ChatAPIError: If the API call fails after all retries are exhausted.
        """
        if stream:
            raise NotImplementedError("Streaming will be implemented in Phase 2")

        self._logger.info(
            "chat_generate_request",
            model=self.config.model,
            message_count=len(messages),
            max_tokens=self.config.max_tokens,
        )

        last_exception: Exception | None = None

        for attempt in range(self.config.max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self.config.model,
                    messages=messages,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                )
                return self._parse_response(response)
            except Exception as exc:
                last_exception = exc
                if not self._should_retry(exc, attempt):
                    break
                if attempt < self.config.max_retries:
                    delay = self._compute_delay(exc, attempt)
                    self._logger.warning(
                        "chat_retry",
                        attempt=attempt + 1,
                        max_retries=self.config.max_retries,
                        delay=round(delay, 2),
                        error=str(exc),
                    )
                    time.sleep(delay)

        raise self._wrap_error(last_exception)

    # ── internal ────────────────────────────────────────────────────

    def _should_retry(self, exception: Exception, attempt: int) -> bool:
        """Decide whether *exception* warrants another attempt."""
        if attempt >= self.config.max_retries:
            return False

        # Timeout — always retry.
        if isinstance(exception, APITimeoutError):
            return True

        # Connection errors (DNS, TCP, TLS) — retry.
        if isinstance(exception, APIConnectionError):
            return True

        if isinstance(exception, APIStatusError):
            # 429 Rate Limit and 5xx — temporary, retry.
            # Other 4xx — permanent, fail fast.
            return exception.status_code == 429 or 500 <= exception.status_code < 600

        # Unknown errors — fail fast (don't retry what we don't understand).
        return False

    def _compute_delay(self, exception: Exception, attempt: int) -> float:
        """Compute the backoff delay for *attempt*, with jitter and upper cap.

        For 429 responses that include a ``Retry-After`` header, the server's
        suggested wait is used (clamped to [0.5, 60] seconds).  Otherwise an
        exponential backoff with full jitter is applied::

            delay = random.uniform(0, min(2 ** attempt, 60))

        The 60-second upper cap prevents pathological wait times when
        ``max_retries`` is configured to a large value.
        """
        if isinstance(exception, APIStatusError) and exception.status_code == 429:
            retry_after = self._parse_retry_after(exception)
            if retry_after is not None:
                return max(0.5, min(retry_after, 60.0))

        # Full jitter — avoids thundering herd when multiple clients retry
        # simultaneously (ref: AWS Architecture Blog — "Exponential Backoff
        # and Jitter").
        return random.uniform(0, min(2**attempt, 60.0))

    @staticmethod
    def _parse_retry_after(exception: APIStatusError, /) -> float | None:
        """Extract ``Retry-After`` seconds from the response headers.

        Returns ``None`` when the header is absent or unparseable.
        """
        headers: dict = getattr(exception.response, "headers", {}) or {}
        value = headers.get("Retry-After") or headers.get("retry-after")
        if value is None:
            return None
        # Prefer integer seconds (RFC 7231 §7.1.3).
        try:
            return float(value)
        except ValueError, TypeError:
            return None

    @staticmethod
    def _parse_response(response: object) -> ChatResult:
        """Inspect the API response and extract a ``ChatResult``."""
        if isinstance(response, str):
            # The API returned a non-JSON body (HTML, plain text, etc.) —
            # typically caused by a misconfigured api_base_url missing the
            # /v1 path prefix.
            raise ChatAPIError(
                f"Chat API returned unexpected text instead of JSON: "
                f"{response[:200]}"
            )

        try:
            choice = response.choices[0]
        except (AttributeError, IndexError, TypeError) as exc:
            raise ChatAPIError(
                f"Chat API response missing expected 'choices' field: {exc}"
            ) from exc

        content = choice.message.content or ""

        usage = getattr(response, "usage", None)
        if usage is not None:
            prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
            completion_tokens = getattr(usage, "completion_tokens", 0) or 0
            total_tokens = getattr(usage, "total_tokens", 0) or 0
        else:
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0

        model = getattr(response, "model", "") or ""

        return ChatResult(
            content=content,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

    @staticmethod
    def _wrap_error(exception: Exception | None) -> ChatAPIError:
        """Convert a third-party exception into a project exception."""
        if exception is None:
            return ChatAPIError("Unknown chat API error")

        if isinstance(exception, APIStatusError):
            return ChatAPIError(
                str(exception),
                status_code=exception.status_code,
            )
        return ChatAPIError(str(exception))
