"""Optional reranking with strict response validation and safe failure messages."""

import math

import httpx


class RerankError(Exception):
    """Reranking failed; the caller may retain vector ordering."""


class RerankAdapter:
    def __init__(
        self,
        *,
        api_base_url: str,
        api_key: str,
        model: str,
        api_format: str = "compatible",
        request_timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._native = api_format == "dashscope"
        path = "/services/rerank/text-rerank/text-rerank" if self._native else "/rerank"
        self._url = api_base_url.rstrip("/") + path
        self._api_key = api_key
        self._model = model
        self._timeout = request_timeout
        self._transport = transport

    def rank(self, query: str, documents: list[str], top_k: int) -> list[int]:
        if not documents:
            return []
        payload = {
            "model": self._model,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
        }
        if self._native:
            payload = {
                "model": self._model,
                "input": {"query": query, "documents": documents},
                "parameters": {"top_n": len(documents), "return_documents": False},
            }
        try:
            with httpx.Client(
                timeout=self._timeout, follow_redirects=False, transport=self._transport
            ) as client:
                response = client.post(
                    self._url,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "User-Agent": "knowra/1.0",
                    },
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
                results = (body["output"] if self._native else body)["results"]
            if not isinstance(results, list) or len(results) != len(documents):
                raise ValueError("Incomplete result")
            indices = set()
            for result in results:
                index = result["index"]
                score = result["relevance_score"]
                if (
                    type(index) is not int
                    or index < 0
                    or index >= len(documents)
                    or index in indices
                    or type(score) not in (int, float)
                    or not math.isfinite(score)
                    or not 0 <= score <= 1
                ):
                    raise ValueError("Invalid result")
                indices.add(index)
            results.sort(key=lambda result: result["relevance_score"], reverse=True)
            return [result["index"] for result in results[:top_k]]
        except httpx.HTTPError, ValueError, KeyError, TypeError:
            raise RerankError("Reranking unavailable") from None
