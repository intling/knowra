"""保留线上重排排序、上下文一致性及故障回退的回归测试。"""

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

from tests.services.test_search_service import (
    get_search_module,
    make_fake_chat_adapter,
    make_fake_chat_config,
    make_fake_db_row,
    make_fake_embedding_adapter,
    make_fake_session,
)


def test_optional_rerank_orders_both_sources_and_prompt():
    rows = [make_fake_db_row(text="first", score=0.1), make_fake_db_row(text="second", score=0.2)]
    reranker = MagicMock()
    reranker.rank.return_value = [1]
    service = get_search_module().SearchService(
        session=make_fake_session(rows=rows),
        owner_user_id=UUID(int=1),
        embedding_adapter=make_fake_embedding_adapter(),
        chat_adapter=make_fake_chat_adapter(),
        chat_config=make_fake_chat_config(),
        rerank_adapter=reranker,
    )
    service._vector_search = MagicMock(return_value=rows)
    service._generate_answer = AsyncMock(return_value=("answer", None, None, [], None, False))
    response = service.search("question", top_k=1)
    assert service._vector_search.call_args.args[1] == 20
    reranker.rank.assert_called_once_with(
        "question",
        [
            rows[0].DocumentChunk.contextualized_text,
            rows[1].DocumentChunk.contextualized_text,
        ],
        1,
    )
    assert response.results[0].chunk_id == rows[1].DocumentEmbedding.chunk_id
    assert response.results[0].score == 0.2
    assert service._generate_answer.call_args.args[1] == [rows[1]]


def test_optional_rerank_failure_keeps_vector_top_k():
    from app.services.rerank_adapter import RerankError

    rows = [make_fake_db_row(score=0.1), make_fake_db_row(score=0.2)]
    reranker = MagicMock()
    reranker.rank.side_effect = RerankError("unavailable")
    service = get_search_module().SearchService(
        session=make_fake_session(rows=rows),
        owner_user_id=UUID(int=1),
        embedding_adapter=make_fake_embedding_adapter(),
        chat_adapter=make_fake_chat_adapter(),
        chat_config=make_fake_chat_config(),
        rerank_adapter=reranker,
    )
    service._generate_answer = AsyncMock(return_value=("answer", None, None, [], None, False))
    response = service.search("question", top_k=1)
    assert len(response.results) == 1
    assert response.results[0].chunk_id == rows[0].DocumentEmbedding.chunk_id
    assert service._generate_answer.call_args.args[1] == [rows[0]]
