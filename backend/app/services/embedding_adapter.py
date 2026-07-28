import random
import time
from dataclasses import dataclass

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from app.services.embedding_config import EmbeddingConfig


class EmbeddingError(Exception):
    """Base exception for all embedding operations."""

    pass


class EmbeddingAPIError(EmbeddingError):
    """Raised when the embedding API call fails after all retries are exhausted."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class EmbeddingInvalidResponseError(EmbeddingError):
    """Raised when the API returns a 2xx response whose payload fails validation
    (e.g. wrong number of vectors, unexpected dimension)."""

    pass


@dataclass(frozen=True)
class EmbeddingResult:
    """A single embedding vector produced by the API.

    Attributes:
        index: Position of the input text in the original request (0-based).
        embedding: The dense vector as a list of floats.
        token_count: Token count for this text, distributed from the batch
            ``usage.total_tokens`` reported by the API.  ``None`` when the
            API response does not include usage data.
    """

    index: int
    embedding: list[float]
    token_count: int | None = None


class EmbeddingAdapter:
    """Encapsulates an OpenAI-compatible ``POST /v1/embeddings`` endpoint.

    The adapter handles batch splitting, retry with exponential backoff, and
    response validation.  No third-party SDK types are exposed to callers —
    every return value is a project-internal dataclass.
    """

    def __init__(
        self,
        *,
        config: EmbeddingConfig,
        client: object | None = None,
    ) -> None:
        self.config = config
        if client is not None:
            self._client = client
        else:
            self._client = OpenAI(
                base_url=config.api_base_url,
                api_key=config.api_key,
                timeout=config.request_timeout,
            )

    # ── public API ──────────────────────────────────────────────────

    def embed(self, texts: list[str]) -> list[EmbeddingResult]:
        """Vectorise *texts* in batches, keeping results in input order.

        When the number of texts exceeds ``config.batch_size`` the list is
        transparently split into multiple API calls whose results are merged
        back in the original order.
        """
        if not texts:
            return []

        batch_size = self.config.batch_size
        if len(texts) <= batch_size:
            return self._embed_batch(texts)

        results: list[EmbeddingResult] = []
        for offset in range(0, len(texts), batch_size):
            sub_batch = texts[offset : offset + batch_size]
            sub_results = self._embed_batch(sub_batch)
            # Re-base indices so they match the caller's original list.
            for item in sub_results:
                results.append(
                    EmbeddingResult(
                        index=offset + item.index,
                        embedding=item.embedding,
                        token_count=item.token_count,
                    )
                )
        return results

    def embed_single(self, text: str) -> EmbeddingResult:
        """Convenience wrapper that vectorises a single string."""
        return self.embed([text])[0]

    # ── internal ────────────────────────────────────────────────────

    def _embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        """Call the API once for *texts*, with retry & validation."""
        last_exception: Exception | None = None

        for attempt in range(self.config.max_retries + 1):
            try:
                response = self._client.embeddings.create(
                    model=self.config.model,
                    input=texts,
                    dimensions=self.config.dimensions,
                    encoding_format=self.config.encoding_format,
                )
                return self._validate_response(response, expected_count=len(texts))
            except EmbeddingInvalidResponseError:
                # Validation failures are not retried — the API returned
                # 2xx but the payload is malformed.
                raise
            except Exception as exc:
                last_exception = exc
                if not self._should_retry(exc, attempt):
                    break
                if attempt < self.config.max_retries:
                    delay = self._compute_delay(exc, attempt)
                    time.sleep(delay)

        raise self._wrap_error(last_exception)

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

    def _validate_response(self, response: object, *, expected_count: int) -> list[EmbeddingResult]:
        """Inspect the API response and raise if the payload is inconsistent."""
        data = response.data

        if len(data) != expected_count:
            raise EmbeddingInvalidResponseError(
                f"Expected {expected_count} embeddings but received {len(data)}"
            )

        # Extract batch-level token usage (if the API returned it).
        total_tokens: int | None = None
        usage = getattr(response, "usage", None)
        if usage is not None:
            total_tokens = getattr(usage, "total_tokens", None)

        results: list[EmbeddingResult] = []
        for i, item in enumerate(data):
            embedding = list(item.embedding)
            if len(embedding) != self.config.dimensions:
                raise EmbeddingInvalidResponseError(
                    f"Expected {self.config.dimensions} dimensions but received {len(embedding)}"
                )
            # Distribute batch-level token count across items so that each
            # chunk gets a fair approximate count (remainder goes to early items).
            tok: int | None = None
            if total_tokens is not None and expected_count > 0:
                base = total_tokens // expected_count
                remainder = total_tokens % expected_count
                tok = base + (1 if i < remainder else 0)
            results.append(
                EmbeddingResult(
                    index=item.index,
                    embedding=embedding,
                    token_count=tok,
                )
            )
        return results

    @staticmethod
    def _wrap_error(exception: Exception | None) -> EmbeddingError:
        """Convert a third-party exception into a project exception."""
        if exception is None:
            return EmbeddingAPIError("Unknown embedding API error")

        if isinstance(exception, APIStatusError):
            return EmbeddingAPIError(
                str(exception),
                status_code=exception.status_code,
            )
        return EmbeddingAPIError(str(exception))
