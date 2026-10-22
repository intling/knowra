import json

import httpx
import pytest

from app.services.rerank_adapter import RerankAdapter, RerankError


def adapter(handler):
    return RerankAdapter(
        api_base_url="https://models.example/v1",
        api_key="synthetic-test-key",
        model="test-reranker",
        transport=httpx.MockTransport(handler),
    )


def test_rerank_preserves_full_text_and_orders_by_relevance():
    full_text = "x" * 800

    def handler(request):
        payload = json.loads(request.content)
        assert request.url.path == "/v1/rerank"
        assert payload == {
            "model": "test-reranker",
            "query": "question",
            "documents": [full_text, "second"],
            "top_n": 2,
        }
        assert request.headers["authorization"] == "Bearer synthetic-test-key"
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 0, "relevance_score": 0.1},
                    {"index": 1, "relevance_score": 0.9},
                ]
            },
        )

    assert adapter(handler).rank("question", [full_text, "second"], 1) == [1]


@pytest.mark.parametrize(
    "results",
    [
        [{"index": 0, "relevance_score": 0.9}] * 2,
        [{"index": 0, "relevance_score": 0.9}, {"index": 2, "relevance_score": 0.1}],
        [{"index": True, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.1}],
        [{"index": 0, "relevance_score": 2.0}, {"index": 1, "relevance_score": 0.1}],
        [{"index": 0, "relevance_score": "0.9"}, {"index": 1, "relevance_score": 0.1}],
        [],
    ],
)
def test_rerank_rejects_invalid_permutations_and_scores(results):
    with pytest.raises(RerankError):
        adapter(lambda _: httpx.Response(200, json={"results": results})).rank(
            "question", ["first", "second"], 2
        )


def test_rerank_http_error_does_not_expose_provider_body():
    with pytest.raises(RerankError) as caught:
        adapter(lambda _: httpx.Response(503, text="sensitive-provider-body")).rank(
            "question", ["first"], 1
        )
    assert "sensitive-provider-body" not in str(caught.value)


def test_rerank_does_not_follow_redirects():
    calls = []

    def handler(request):
        calls.append(request.url.host)
        return httpx.Response(307, headers={"Location": "https://other.example"})

    with pytest.raises(RerankError):
        adapter(handler).rank("question", ["first"], 1)
    assert calls == ["models.example"]


def test_empty_candidates_do_not_call_provider():
    def handler(_):
        pytest.fail("empty reranking must not make a request")

    assert adapter(handler).rank("question", [], 2) == []


def test_dashscope_native_payload_and_nested_response():
    def handler(request):
        assert request.url.path == "/api/v1/services/rerank/text-rerank/text-rerank"
        assert json.loads(request.content) == {
            "model": "qwen3.7-text-rerank",
            "input": {"query": "question", "documents": ["first", "second"]},
            "parameters": {"top_n": 2, "return_documents": False},
        }
        return httpx.Response(
            200,
            json={
                "output": {
                    "results": [
                        {"index": 1, "relevance_score": 0.9},
                        {"index": 0, "relevance_score": 0.1},
                    ]
                }
            },
        )

    native = RerankAdapter(
        api_base_url="https://models.example/api/v1",
        api_key="synthetic-test-key",
        model="qwen3.7-text-rerank",
        api_format="dashscope",
        transport=httpx.MockTransport(handler),
    )
    assert native.rank("question", ["first", "second"], 1) == [1]
