"""资料总结 RED 契约：真实 SQLite 文档、分块与缓存，不调用线上模型。"""

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from app.core.config import get_settings
from app.core.errors import AppError
from app.models.document_chunking import DocumentChunk, DocumentChunkJob
from app.models.user import utc_now
from app.services.cache_manager import CacheManager
from app.services.document_chunk_storage import ChunkArtifactStorage
from app.services.search import SearchService
from tests.auth_helpers import make_account, seed_knowledge_chain
from tests.search_helpers import (
    make_fake_chat_adapter,
    make_fake_chat_config,
    make_fake_embedding_adapter,
)


@pytest.fixture
def library(auth_db, tmp_path, fast_password_hasher, monkeypatch):
    """仅替换 SQLite 不支持的 pgvector 操作，保留资料查询与用户过滤。"""
    owner = make_account(auth_db)
    vector_search = MagicMock(return_value=[])
    monkeypatch.setattr(SearchService, "_vector_search", vector_search)
    monkeypatch.setattr(get_settings(), "document_chunk_artifact_storage_dir", str(tmp_path))

    def seed(name, text, *, user=None, chunk_count=2):
        chain = seed_knowledge_chain(auth_db, tmp_path / name, user or owner, vectors=chunk_count)
        upload, parsed, _job, chunks, _embeddings = chain
        upload.original_filename = name
        parsed.title = name
        auth_db.add(upload)
        auth_db.add(parsed)
        for index, chunk in enumerate(chunks):
            chunk.text = f"{text}，第 {index + 1} 段。"
            chunk.contextualized_text = chunk.text
            auth_db.add(chunk)
        auth_db.commit()
        return chain

    def service(*, user=None, cache=None):
        embedding = make_fake_embedding_adapter()
        chat = make_fake_chat_adapter(content="根据这些资料，核心观点如下。")
        return (
            SearchService(
                session=auth_db,
                owner_user_id=(user or owner).id,
                embedding_adapter=embedding,
                chat_adapter=chat,
                chat_config=make_fake_chat_config(),
                response_cache=cache,
            ),
            embedding,
            chat,
        )

    return owner, seed, service, vector_search


def summarize(service, **kwargs):
    """服务尚未接收范围参数时，给评审者提供具体的契约缺口。"""
    try:
        return service.search(query="总结这些资料的核心观点", **kwargs)
    except TypeError as error:
        if "document_ids" in str(error):
            pytest.fail("总结入口尚未支持 document_ids；预期使用已校验的文档范围")
        raise


def prompt_text(chat):
    """读取模型网络边界的实际输入，检查总结是否使用了真实文档。"""
    assert chat.generate_async.call_args is not None, "存在可读资料时必须生成总结"
    return "\n".join(message["content"] for message in chat.generate_async.call_args.args[0])


def test_summary_uses_all_visible_documents_even_when_top_k_is_one(library):
    """验证推荐总结问题按文档读内容，Top-K=1 也不把三份资料误缩成一段。"""
    _owner, seed, service_factory, vector_search = library
    docs = [
        seed("数据结构.md", "列表可变、元组不可变"),
        seed("异常处理.md", "finally 用于可靠清理"),
        seed("虚拟环境.md", "独立环境隔离依赖"),
    ]
    service, embedding, chat = service_factory()

    response = summarize(service, top_k=1)

    assert response.model_dump().get("answer_mode") == "summary"
    assert {item.parsed_document_id for item in response.results} == {d[1].id for d in docs}
    prompt = prompt_text(chat)
    for phrase in ("列表可变、元组不可变", "finally 用于可靠清理", "独立环境隔离依赖"):
        assert phrase in prompt, f"总结遗漏真实资料内容：{phrase}"
    assert response.model_dump().get("summary_coverage") == {
        "document_count": 3,
        "included_document_count": 3,
        "total_chunks": 6,
        "included_chunks": 6,
        "truncated": False,
    }
    embedding.embed_single.assert_not_called()
    vector_search.assert_not_called()


def test_summary_honors_explicit_document_scope(library):
    """验证指定文档后仅该文档进入模型、来源和总结覆盖统计。"""
    _owner, seed, service_factory, _vector_search = library
    selected = seed("选中的资料.md", "允许进入总结的观点")
    seed("未选中的资料.md", "不应进入总结的观点")
    service, _, chat = service_factory()

    response = summarize(service, document_ids=[selected[1].id])

    assert {item.parsed_document_id for item in response.results} == {selected[1].id}
    prompt = prompt_text(chat)
    assert "允许进入总结的观点" in prompt
    assert "不应进入总结的观点" not in prompt
    assert response.model_dump()["summary_coverage"]["document_count"] == 1


@pytest.mark.parametrize("query", ["你好，帮我总结这些资料", "Summarize these documents"])
def test_document_summary_intent_takes_priority_over_greeting(library, query):
    """验证资料指代优先于问候，并支持英文资料概览，不因问候前缀跳过文档。"""
    _owner, seed, service_factory, _vector_search = library
    document = seed("待总结.md", "真实的概览依据")
    service, _, chat = service_factory()

    response = service.search(query=query)

    assert response.model_dump().get("answer_mode") == "summary"
    assert response.results[0].parsed_document_id == document[1].id
    assert "真实的概览依据" in prompt_text(chat)


def test_duplicate_document_ids_do_not_duplicate_summary_context(library):
    """验证重复选择同一文档不会重复上下文、来源或覆盖计数。"""
    _owner, seed, service_factory, _vector_search = library
    document = seed("重复选择.md", "唯一的资料观点", chunk_count=1)
    service, _, _ = service_factory()

    response = summarize(service, document_ids=[document[1].id, document[1].id])

    assert len(response.results) == 1
    assert response.model_dump()["summary_coverage"]["document_count"] == 1
    assert response.model_dump()["summary_coverage"]["total_chunks"] == 1


def test_summary_excludes_other_users_and_deleted_uploads(library, auth_db):
    """验证默认总结也遵守用户和软删除边界，覆盖计数不泄露不可见资料。"""
    _owner, seed, service_factory, _vector_search = library
    visible = seed("我的资料.md", "当前用户可见观点")
    other = make_account(auth_db)
    seed("他人的资料.md", "他人私密观点", user=other)
    deleted = seed("已删除资料.md", "已删除的私密观点")
    deleted[0].deleted_at = utc_now()
    auth_db.add(deleted[0])
    auth_db.commit()
    service, _, chat = service_factory()

    response = summarize(service)

    assert response.model_dump().get("answer_mode") == "summary"
    assert {item.parsed_document_id for item in response.results} == {visible[1].id}
    prompt = prompt_text(chat)
    assert "当前用户可见观点" in prompt
    assert "他人私密观点" not in prompt
    assert "已删除的私密观点" not in prompt
    assert response.model_dump()["summary_coverage"]["document_count"] == 1


def test_summary_can_read_chunked_documents_without_vectors(library, auth_db):
    """验证资料已分块但尚未向量化时可以直接总结，避免把向量数当作文档可读性。"""
    _owner, seed, service_factory, _vector_search = library
    document = seed("尚未向量化.md", "尚未向量化的真实内容")
    for embedding in document[4]:
        auth_db.delete(embedding)
    auth_db.commit()
    service, _, chat = service_factory()

    response = summarize(service)

    assert response.model_dump().get("answer_mode") == "summary"
    assert "尚未向量化的真实内容" in prompt_text(chat)
    assert response.results[0].parsed_document_id == document[1].id


def test_summary_uses_latest_successful_chunk_job(library, auth_db):
    """验证重分块只读取最新成功版本，不把历史版本重复或混入当前总结。"""
    owner, seed, service_factory, _vector_search = library
    _upload, parsed, old_job, _chunks, _embeddings = seed("版本资料.md", "旧版本内容")
    new_job = DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=owner.id,
        status="succeeded",
        chunker_name="fixture",
        chunk_count=1,
        created_at=old_job.created_at + timedelta(seconds=1),
    )
    auth_db.add(new_job)
    auth_db.commit()
    new_chunk = DocumentChunk(
        chunk_job_id=new_job.id,
        parsed_document_id=parsed.id,
        owner_user_id=owner.id,
        sequence_index=0,
        text="最新成功版本的真实观点",
        contextualized_text="最新成功版本的真实观点",
    )
    auth_db.add(new_chunk)
    auth_db.commit()
    service, _, chat = service_factory()

    response = summarize(service)

    assert response.model_dump().get("answer_mode") == "summary"
    assert "最新成功版本的真实观点" in prompt_text(chat)
    assert "旧版本内容" not in prompt_text(chat)
    assert response.model_dump()["summary_coverage"]["total_chunks"] == 1


def test_summary_reads_external_chunk_artifacts(library, auth_db, tmp_path):
    """验证长正文仅保存为工件时，总结仍读取实际内容并能追溯到该分块。"""
    owner, seed, service_factory, _vector_search = library
    document = seed("外置正文.md", "被外置的真实正文", chunk_count=1)
    chunk = document[3][0]
    stored = ChunkArtifactStorage(tmp_path).save_texts(
        owner_user_id=owner.id,
        parsed_document_id=document[1].id,
        chunk_job_id=document[2].id,
        sequence_index=0,
        text="被外置的真实正文",
        contextualized_text="被外置的真实正文",
        inline_text_max_bytes=1,
    )
    chunk.text = stored.text
    chunk.text_storage_key = stored.text_storage_key
    chunk.contextualized_text = stored.contextualized_text
    chunk.contextualized_text_storage_key = stored.contextualized_text_storage_key
    auth_db.add(chunk)
    auth_db.commit()
    service, _, chat = service_factory()

    response = summarize(service)

    assert response.model_dump().get("answer_mode") == "summary"
    assert "被外置的真实正文" in prompt_text(chat)
    assert response.results[0].chunk_id == chunk.id


def test_unreadable_summary_artifact_returns_actionable_error(library, auth_db):
    """验证损坏的资料工件产生明确错误，不能静默当作空文档或通用回答。"""
    _owner, seed, service_factory, _vector_search = library
    document = seed("工件丢失.md", "原始正文", chunk_count=1)
    chunk = document[3][0]
    chunk.text = None
    chunk.contextualized_text = None
    chunk.text_storage_key = "chunks/missing.txt"
    chunk.contextualized_text_storage_key = "chunks/missing-context.txt"
    auth_db.add(chunk)
    auth_db.commit()
    service, _, _ = service_factory()

    with pytest.raises(AppError) as caught:
        summarize(service)

    assert caught.value.status_code == 503
    assert "资料" in caught.value.detail and "重试" in caught.value.detail
    assert "missing.txt" not in caught.value.detail, "错误不能暴露存储路径"


def test_large_summary_has_bounded_context_and_truthful_coverage(library):
    """验证超出正文预算的总结上下文有界，并向模型与用户披露部分覆盖。"""
    _owner, seed, service_factory, _vector_search = library
    seed("大型资料.md", "长资料内容" * 3000, chunk_count=8)
    service, _, chat = service_factory()

    response = summarize(service)

    assert response.model_dump().get("answer_mode") == "summary"
    coverage = response.model_dump()["summary_coverage"]
    assert coverage["truncated"] is True
    assert coverage["document_count"] == coverage["included_document_count"] == 1
    assert coverage["total_chunks"] == 8
    assert 1 <= coverage["included_chunks"] <= 8
    prompt = prompt_text(chat)
    assert len(prompt) <= 65000, "60,000 字符正文预算外只允许有限的规则和元数据开销"
    assert "部分" in prompt, "提示词必须披露未阅读全文，不能暗示完整总结"


def test_empty_library_summary_guides_upload_instead_of_inventing_content(library):
    """验证没有资料时推荐总结问题提供可操作引导，并不调用模型猜测文档内容。"""
    _owner, _seed, service_factory, _vector_search = library
    service, _, chat = service_factory()

    response = summarize(service)

    assert response.model_dump().get("answer_mode") == "clarification"
    assert any(word in response.answer for word in ("上传", "选择", "处理"))
    assert response.results == []
    assert response.answer_tokens is None
    chat.generate_async.assert_not_called()


def test_oversized_library_asks_for_smaller_scope_before_model_call(library):
    """验证默认范围超过 20 份文档时先引导缩小范围，避免无界读取和模型调用。"""
    _owner, seed, service_factory, _vector_search = library
    for index in range(21):
        seed(f"资料-{index}.md", f"文档 {index} 的内容", chunk_count=1)
    service, _, chat = service_factory()

    response = summarize(service)

    assert response.model_dump().get("answer_mode") == "clarification"
    assert any(word in response.answer for word in ("选择", "范围", "指定"))
    assert response.results == []
    chat.generate_async.assert_not_called()


def test_summary_cache_keeps_document_scopes_separate(library):
    """验证同会话同问题不同文档范围不能命中彼此总结，相同范围仍能复用缓存。"""
    _owner, seed, service_factory, _vector_search = library
    document_a = seed("文档甲.md", "甲的真实观点")
    document_b = seed("文档乙.md", "乙的真实观点")
    service, _, chat = service_factory(cache=CacheManager(ttl_seconds=60))

    first = summarize(service, document_ids=[document_a[1].id], session_id="same-session")
    second = summarize(service, document_ids=[document_b[1].id], session_id="same-session")
    again = summarize(service, document_ids=[document_a[1].id], session_id="same-session")

    assert {item.parsed_document_id for item in first.results} == {document_a[1].id}
    assert {item.parsed_document_id for item in second.results} == {document_b[1].id}
    assert {item.parsed_document_id for item in again.results} == {document_a[1].id}
    assert chat.generate_async.await_count == 2


def test_summary_cache_refreshes_when_visible_scope_changes(library, auth_db):
    """验证删除资料后，即使旧 Embedding 指纹未变，也不返回旧总结来源。"""
    _owner, seed, service_factory, _ = library
    first = seed("保留.md", "保留的观点", chunk_count=1)
    removed = seed("删除.md", "删除的观点", chunk_count=1)
    service, _, chat = service_factory(cache=CacheManager(ttl_seconds=60))
    summarize(service, session_id="same")
    removed[0].deleted_at = utc_now()
    auth_db.add(removed[0])
    auth_db.commit()

    response = summarize(service, session_id="same")

    assert {item.parsed_document_id for item in response.results} == {first[1].id}
    assert chat.generate_async.await_count == 2


def test_summary_cache_refreshes_after_rechunk_without_embedding(library, auth_db):
    """验证仅完成重分块时缓存也更新，不依赖下一次向量化触发指纹变化。"""
    owner, seed, service_factory, _ = library
    _, parsed, old_job, *_ = seed("重分块.md", "旧内容", chunk_count=1)
    service, _, chat = service_factory(cache=CacheManager(ttl_seconds=60))
    summarize(service, session_id="same")
    job = DocumentChunkJob(
        owner_user_id=owner.id,
        parsed_document_id=parsed.id,
        status="succeeded",
        created_at=old_job.created_at + timedelta(seconds=1),
        chunk_count=1,
    )
    auth_db.add(job)
    auth_db.commit()
    chunk = DocumentChunk(
        owner_user_id=owner.id,
        parsed_document_id=parsed.id,
        chunk_job_id=job.id,
        sequence_index=0,
        text="新的观点",
    )
    auth_db.add(chunk)
    auth_db.commit()

    response = summarize(service, session_id="same")

    assert response.results[0].chunk_id == chunk.id
    assert chat.generate_async.await_count == 2
