"""按认证用户读取最新成功分块，为总结分配有界正文预算。"""

import hashlib
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID

from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.errors import AppError
from app.models.document_chunking import DocumentChunk, DocumentChunkJob
from app.models.document_parsing import ParsedDocument
from app.models.uploaded_file import UploadedFile
from app.schemas.search import SummaryCoverage
from app.services.document_chunk_storage import ChunkArtifactStorage, ChunkArtifactStorageError

BODY_BUDGET = 60_000


def visible_documents(session: Session, owner: UUID, document_ids: list[UUID] | None):
    stmt = (
        select(ParsedDocument, UploadedFile.original_filename)
        .join(UploadedFile, ParsedDocument.uploaded_file_id == UploadedFile.id)
        .where(
            ParsedDocument.owner_user_id == owner,
            UploadedFile.owner_user_id == owner,
            UploadedFile.deleted_at.is_(None),
        )
        .order_by(ParsedDocument.id)
    )
    if document_ids is not None:
        stmt = stmt.where(ParsedDocument.id.in_(document_ids))
    return session.exec(stmt.limit(21)).all()


def validate_scope(session: Session, owner: UUID, document_ids: list[UUID] | None):
    if document_ids is None:
        return
    documents = visible_documents(session, owner, document_ids)
    if {doc.id for doc, _ in documents} != set(document_ids):
        raise AppError(404, "document_not_found", "指定资料不存在或不可访问，请重新选择资料")


def summary_revision(session: Session, owner: UUID, document_ids: list[UUID] | None) -> str:
    """在读取缓存前检查资料集合及分块版本，无需依赖向量化状态。"""
    revisions = []
    for document, name in visible_documents(session, owner, document_ids):
        job = _latest_job(session, owner, document.id)
        revisions.append(
            f"{document.id}:{name}:{job.id if job else None}:{job.updated_at if job else None}"
        )
    return hashlib.sha256("|".join(revisions).encode()).hexdigest()[:16]


def _latest_job(session: Session, owner: UUID, document_id: UUID):
    return session.exec(
        select(DocumentChunkJob)
        .where(
            DocumentChunkJob.owner_user_id == owner,
            DocumentChunkJob.parsed_document_id == document_id,
            DocumentChunkJob.status == "succeeded",
        )
        .order_by(DocumentChunkJob.created_at.desc(), DocumentChunkJob.id.desc())
        .limit(1)
    ).first()


@dataclass
class SummaryContext:
    rows: list
    coverage: SummaryCoverage
    guidance: str | None = None


def _read_text(chunk: DocumentChunk, budget: int) -> tuple[str, bool]:
    text = chunk.contextualized_text or chunk.text
    key = chunk.contextualized_text_storage_key or chunk.text_storage_key
    if not text and key:
        storage = ChunkArtifactStorage(get_settings().document_chunk_artifact_storage_dir)
        try:
            path = storage.path_for(key).resolve()
            if not path.is_relative_to(storage.root_dir.resolve()):
                raise ChunkArtifactStorageError("Invalid artifact location")
            with path.open(encoding="utf-8") as stream:
                text = stream.read(budget + 1)
        except (OSError, UnicodeError, ChunkArtifactStorageError) as exc:
            raise AppError(
                503, "summary_content_unavailable", "资料内容暂不可读取，请稍后重试或重新处理资料"
            ) from exc
    text = text or ""
    return text[:budget], len(text) > budget


def build_summary_context(
    session: Session, owner: UUID, document_ids: list[UUID] | None
) -> SummaryContext:
    documents = visible_documents(session, owner, document_ids)
    coverage = SummaryCoverage(
        document_count=len(documents),
        included_document_count=0,
        total_chunks=0,
        included_chunks=0,
        truncated=False,
    )
    if len(documents) > 20:
        return SummaryContext([], coverage, "资料超过 20 份，请选择或指定更小的总结范围后重试。")
    rows = []
    for document, name in documents:
        job = _latest_job(session, owner, document.id)
        if job is None:
            coverage.truncated = True
            continue
        chunks = session.exec(
            select(DocumentChunk)
            .where(
                DocumentChunk.owner_user_id == owner,
                DocumentChunk.parsed_document_id == document.id,
                DocumentChunk.chunk_job_id == job.id,
            )
            .order_by(DocumentChunk.sequence_index, DocumentChunk.id)
        ).all()
        coverage.total_chunks += len(chunks)
        remaining = BODY_BUDGET // len(documents)
        included = False
        for chunk in chunks:
            if remaining <= 0:
                coverage.truncated = True
                continue
            text, truncated = _read_text(chunk, remaining)
            coverage.truncated |= truncated
            if not text.strip():
                continue
            # 独立上下文副本，不能修改 ORM 对象或持久化截取后的正文。
            context_chunk = SimpleNamespace(
                text=text,
                contextualized_text=text,
                token_count=chunk.token_count,
                heading_path=chunk.heading_path,
                page_numbers=chunk.page_numbers,
            )
            rows.append(
                SimpleNamespace(
                    DocumentChunk=context_chunk,
                    DocumentEmbedding=SimpleNamespace(
                        chunk_id=chunk.id,
                        parsed_document_id=document.id,
                        sequence_index=chunk.sequence_index,
                    ),
                    document_name=name,
                    score=0.0,
                )
            )
            remaining -= len(text)
            coverage.included_chunks += 1
            included = True
        coverage.included_document_count += int(included)
    coverage.truncated |= coverage.included_document_count < coverage.document_count
    return SummaryContext(rows, coverage)
