from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.models.document_chunking import DocumentChunk, DocumentChunkJob, DocumentChunkJobStatus
from app.models.document_parsing import ParsedDocument
from app.models.uploaded_file import UploadedFile
from app.models.user import utc_now
from app.schemas.document_chunking import (
    DocumentChunkConflictRead,
    DocumentChunkJobRead,
    DocumentChunkPageRead,
    DocumentChunkRead,
    RechunkRequest,
)
from app.services.document_chunker import DocumentChunkingConfig
from app.services.uploads import LocalFileStorage
from app.services.users import CurrentUserUnavailableError, get_current_user

router = APIRouter(tags=["document-chunking"])
SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get(
    "/document-chunk-jobs/{job_id}",
    response_model=DocumentChunkJobRead,
)
def read_document_chunk_job(job_id: UUID, session: SessionDep) -> DocumentChunkJobRead:
    current_user = require_current_user(session)
    job = session.exec(
        select(DocumentChunkJob).where(
            DocumentChunkJob.id == job_id,
            DocumentChunkJob.owner_user_id == current_user.id,
        )
    ).first()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chunk job not found")

    return DocumentChunkJobRead.model_validate(job, from_attributes=True)


@router.get(
    "/parsed-documents/{parsed_document_id}/chunk-job",
    response_model=DocumentChunkJobRead,
)
def read_latest_parsed_document_chunk_job(
    parsed_document_id: UUID,
    session: SessionDep,
) -> DocumentChunkJobRead:
    current_user = require_current_user(session)
    parsed_document = get_owned_parsed_document(
        session=session,
        parsed_document_id=parsed_document_id,
        owner_user_id=current_user.id,
    )
    job = get_latest_chunk_job(session=session, parsed_document_id=parsed_document.id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chunk job not found")

    return DocumentChunkJobRead.model_validate(job, from_attributes=True)


@router.get(
    "/parsed-documents/{parsed_document_id}/chunks",
    response_model=DocumentChunkPageRead,
)
def read_parsed_document_chunks(
    parsed_document_id: UUID,
    session: SessionDep,
    offset: int = 0,
    limit: int = 50,
) -> DocumentChunkPageRead:
    current_user = require_current_user(session)
    parsed_document = get_owned_parsed_document(
        session=session,
        parsed_document_id=parsed_document_id,
        owner_user_id=current_user.id,
    )
    active_job = get_active_chunk_job(session=session, parsed_document_id=parsed_document.id)
    normalized_offset = max(0, offset)
    bounded_limit = max(1, min(limit, 200))
    if active_job is None:
        return DocumentChunkPageRead(
            items=[],
            total=0,
            offset=normalized_offset,
            limit=bounded_limit,
        )

    total = session.exec(
        select(func.count(DocumentChunk.id)).where(DocumentChunk.chunk_job_id == active_job.id)
    ).one()
    chunks = session.exec(
        select(DocumentChunk)
        .where(DocumentChunk.chunk_job_id == active_job.id)
        .order_by(DocumentChunk.sequence_index)
        .offset(normalized_offset)
        .limit(bounded_limit)
    ).all()
    return DocumentChunkPageRead(
        items=[to_chunk_read(chunk) for chunk in chunks],
        total=total,
        offset=normalized_offset,
        limit=bounded_limit,
    )


@router.get(
    "/document-chunks/{chunk_id}",
    response_model=DocumentChunkRead,
)
def read_document_chunk(chunk_id: UUID, session: SessionDep) -> DocumentChunkRead:
    current_user = require_current_user(session)
    chunk = session.exec(
        select(DocumentChunk).where(
            DocumentChunk.id == chunk_id,
            DocumentChunk.owner_user_id == current_user.id,
        )
    ).first()
    if chunk is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chunk not found")
    return to_chunk_read(chunk)


@router.post(
    "/parsed-documents/{parsed_document_id}/rechunk",
    response_model=DocumentChunkJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def rechunk_parsed_document(
    parsed_document_id: UUID,
    session: SessionDep,
    settings: SettingsDep,
    request: RechunkRequest | None = None,
) -> DocumentChunkJobRead | JSONResponse:
    current_user = require_current_user(session)
    parsed_document = get_owned_parsed_document(
        session=session,
        parsed_document_id=parsed_document_id,
        owner_user_id=current_user.id,
    )
    running_job = get_running_chunk_job(session=session, parsed_document_id=parsed_document.id)
    if running_job is not None:
        payload = DocumentChunkConflictRead(
            detail="Document chunk job already running",
            job=DocumentChunkJobRead.model_validate(running_job, from_attributes=True),
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=jsonable_encoder(payload),
        )

    if not original_upload_file_is_available(
        session=session,
        parsed_document=parsed_document,
        settings=settings,
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original uploaded file is unavailable",
        )

    job = create_queued_rechunk_job(
        session=session,
        parsed_document=parsed_document,
        config=make_chunking_config(settings=settings, request=request),
    )
    return DocumentChunkJobRead.model_validate(job, from_attributes=True)


def require_current_user(session: Session):
    try:
        return get_current_user(session)
    except CurrentUserUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Current user is unavailable",
        ) from exc


def get_owned_parsed_document(
    *,
    session: Session,
    parsed_document_id: UUID,
    owner_user_id: UUID,
) -> ParsedDocument:
    parsed_document = session.exec(
        select(ParsedDocument).where(
            ParsedDocument.id == parsed_document_id,
            ParsedDocument.owner_user_id == owner_user_id,
        )
    ).first()
    if parsed_document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parsed document not found",
        )
    return parsed_document


def get_active_chunk_job(
    *,
    session: Session,
    parsed_document_id: UUID,
) -> DocumentChunkJob | None:
    return session.exec(
        select(DocumentChunkJob)
        .where(
            DocumentChunkJob.parsed_document_id == parsed_document_id,
            DocumentChunkJob.status == DocumentChunkJobStatus.SUCCEEDED.value,
            DocumentChunkJob.status != DocumentChunkJobStatus.SUPERSEDED.value,
        )
        .order_by(col(DocumentChunkJob.created_at).desc())
    ).first()


def get_latest_chunk_job(
    *,
    session: Session,
    parsed_document_id: UUID,
) -> DocumentChunkJob | None:
    return session.exec(
        select(DocumentChunkJob)
        .where(DocumentChunkJob.parsed_document_id == parsed_document_id)
        .order_by(col(DocumentChunkJob.created_at).desc(), col(DocumentChunkJob.id).desc())
    ).first()


def get_running_chunk_job(
    *,
    session: Session,
    parsed_document_id: UUID,
) -> DocumentChunkJob | None:
    return session.exec(
        select(DocumentChunkJob).where(
            DocumentChunkJob.parsed_document_id == parsed_document_id,
            col(DocumentChunkJob.status).in_(
                [
                    DocumentChunkJobStatus.QUEUED.value,
                    DocumentChunkJobStatus.RUNNING.value,
                ]
            ),
        )
    ).first()


def original_upload_file_is_available(
    *,
    session: Session,
    parsed_document: ParsedDocument,
    settings: Settings,
) -> bool:
    uploaded_file = session.get(UploadedFile, parsed_document.uploaded_file_id)
    if uploaded_file is None:
        return False

    path = LocalFileStorage(settings.upload_storage_dir).path_for(uploaded_file.storage_key)
    return path.is_file()


def create_queued_rechunk_job(
    *,
    session: Session,
    parsed_document: ParsedDocument,
    config: DocumentChunkingConfig,
) -> DocumentChunkJob:
    now = utc_now()
    job = DocumentChunkJob(
        parsed_document_id=parsed_document.id,
        owner_user_id=parsed_document.owner_user_id,
        status=DocumentChunkJobStatus.QUEUED.value,
        chunker_name="docling_hybrid",
        chunker_version="docling-core",
        chunk_config_json=config.snapshot(),
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def make_chunking_config(
    *,
    settings: Settings,
    request: RechunkRequest | None = None,
) -> DocumentChunkingConfig:
    max_tokens = (
        request.max_tokens if request and request.max_tokens else settings.document_chunk_max_tokens
    )
    return DocumentChunkingConfig(
        tokenizer_model=request.tokenizer_model
        if request and request.tokenizer_model
        else settings.document_chunk_tokenizer_model,
        max_tokens=max_tokens,
        merge_peers=request.merge_peers
        if request and request.merge_peers is not None
        else settings.document_chunk_merge_peers,
        repeat_table_header=request.repeat_table_header
        if request and request.repeat_table_header is not None
        else settings.document_chunk_repeat_table_header,
        inline_text_max_bytes=settings.document_chunk_inline_text_max_bytes,
        tokenizer_cache_dir=settings.document_parse_docling_cache_dir,
    )


def to_chunk_read(chunk: DocumentChunk) -> DocumentChunkRead:
    return DocumentChunkRead(
        id=chunk.id,
        chunk_job_id=chunk.chunk_job_id,
        parsed_document_id=chunk.parsed_document_id,
        owner_user_id=chunk.owner_user_id,
        sequence_index=chunk.sequence_index,
        text=chunk.text,
        contextualized_text=chunk.contextualized_text,
        token_count=chunk.token_count,
        heading_path=chunk.heading_path,
        page_numbers=chunk.page_numbers,
        chunk_type=chunk.chunk_type,
        source_segment_indices=chunk.source_segment_indices,
        metadata=chunk.metadata_json,
        created_at=chunk.created_at,
    )
