# 本文件验证 ChunkArtifactStorage 的混合文本存储策略。
# 短文本应留在数据库字段，超过阈值的正文/上下文化文本应写入稳定路径并返回可读取 key。

from importlib import import_module
from uuid import uuid4


# 短 text/contextualized_text 小于阈值时，应直接返回内联字段。
# 测试同时确认临时存储目录保持为空，证明小内容不会额外落盘。
def test_chunk_artifact_storage_inlines_short_text_and_contextualized_text(tmp_path) -> None:
    storage_module = import_module("app.services.document_chunk_storage")
    storage = storage_module.ChunkArtifactStorage(root_dir=tmp_path)

    stored = storage.save_texts(
        owner_user_id=uuid4(),
        parsed_document_id=uuid4(),
        chunk_job_id=uuid4(),
        sequence_index=0,
        text="short text",
        contextualized_text="context short text",
        inline_text_max_bytes=2048,
    )

    assert stored.text == "short text"
    assert stored.text_storage_key is None
    assert stored.contextualized_text == "context short text"
    assert stored.contextualized_text_storage_key is None
    assert list(tmp_path.rglob("*")) == []


# 正文和上下文化文本超过阈值时，应分别写入可预测的 storage key。
# 测试同时确认写入文件的内容与输入完全一致。
def test_chunk_artifact_storage_writes_long_texts_to_stable_storage_keys(tmp_path) -> None:
    storage_module = import_module("app.services.document_chunk_storage")
    storage = storage_module.ChunkArtifactStorage(root_dir=tmp_path)
    owner_user_id = uuid4()
    parsed_document_id = uuid4()
    chunk_job_id = uuid4()

    stored = storage.save_texts(
        owner_user_id=owner_user_id,
        parsed_document_id=parsed_document_id,
        chunk_job_id=chunk_job_id,
        sequence_index=7,
        text="x" * 9,
        contextualized_text="y" * 10,
        inline_text_max_bytes=8,
    )

    assert stored.text is None
    assert stored.contextualized_text is None
    assert stored.text_storage_key == (
        f"chunks/{owner_user_id}/{parsed_document_id}/{chunk_job_id}/000007_text.txt"
    )
    assert stored.contextualized_text_storage_key == (
        f"chunks/{owner_user_id}/{parsed_document_id}/{chunk_job_id}/000007_contextualized.txt"
    )
    assert storage.path_for(stored.text_storage_key).read_text(encoding="utf-8") == "x" * 9
    assert (
        storage.path_for(stored.contextualized_text_storage_key).read_text(encoding="utf-8")
        == "y" * 10
    )
