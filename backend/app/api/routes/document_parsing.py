from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlmodel import Session, select

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.models.document_parsing import DocumentParseJob, DocumentSegment, ParsedDocument
from app.models.uploaded_file import UploadedFile
from app.schemas.document_parsing import (
    DocumentParseConflictRead,
    DocumentParseJobRead,
    DocumentSegmentPageRead,
    DocumentSegmentRead,
    ParsedDocumentRead,
    UploadedFileParseInfo,
)
from app.services.document_parse_dispatcher import BackgroundTasksParseJobDispatcher
from app.services.document_parser import UnsupportedDocumentFormatError
from app.services.document_parsing import (
    DocumentParseConflictError,
    DocumentParseNotFoundError,
    DocumentParseService,
    DocumentParseTooLargeError,
    DocumentParsingDisabledError,
)
from app.services.uploads import LocalFileStorage
from app.services.users import CurrentUserUnavailableError, get_current_user

router = APIRouter(tags=["document-parsing"])
SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post(
    "/uploads/{upload_id}/parse",
    response_model=DocumentParseJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_document_parse_job(
    upload_id: UUID,
    background_tasks: BackgroundTasks,
    session: SessionDep,
    settings: SettingsDep,
) -> DocumentParseJobRead | JSONResponse:
    current_user = require_current_user(session)
    service = make_document_parse_service(session=session, settings=settings)

    try:
        job = service.create_parse_job(current_user=current_user, upload_id=upload_id)
    except DocumentParsingDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document parsing is disabled",
        ) from exc
    except DocumentParseNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found"
        ) from exc
    except UnsupportedDocumentFormatError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported document format",
        ) from exc
    except DocumentParseTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="File size exceeds document_parse_max_bytes",
        ) from exc
    except DocumentParseConflictError as exc:
        payload = DocumentParseConflictRead(
            detail="Document parse job already running",
            job=DocumentParseJobRead.model_validate(exc.job, from_attributes=True),
            uploaded_file=to_uploaded_file_parse_info(exc.uploaded_file),
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=jsonable_encoder(payload),
        )

    BackgroundTasksParseJobDispatcher(background_tasks).enqueue(job.id)
    return DocumentParseJobRead.model_validate(job, from_attributes=True)


@router.get(
    "/document-parse-jobs/{job_id}",
    response_model=DocumentParseJobRead,
)
def read_document_parse_job(job_id: UUID, session: SessionDep) -> DocumentParseJobRead:
    current_user = require_current_user(session)
    statement = select(DocumentParseJob).where(
        DocumentParseJob.id == job_id,
        DocumentParseJob.owner_user_id == current_user.id,
    )
    job = session.exec(statement).first()
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document parse job not found",
        )

    return DocumentParseJobRead.model_validate(job, from_attributes=True)


@router.get(
    "/uploads/{upload_id}/parsed-document",
    response_model=ParsedDocumentRead,
)
def read_uploaded_file_parsed_document(
    upload_id: UUID,
    session: SessionDep,
) -> ParsedDocumentRead:
    current_user = require_current_user(session)
    upload = get_owned_upload(session=session, upload_id=upload_id, owner_user_id=current_user.id)
    statement = (
        select(ParsedDocument)
        .where(
            ParsedDocument.uploaded_file_id == upload.id,
            ParsedDocument.owner_user_id == current_user.id,
        )
        .order_by(ParsedDocument.created_at.desc())
    )
    parsed_document = session.exec(statement).first()
    if parsed_document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not parsed")

    segment_count = session.exec(
        select(func.count(DocumentSegment.id)).where(
            DocumentSegment.parsed_document_id == parsed_document.id
        )
    ).one()
    return to_parsed_document_read(parsed_document, segment_count=segment_count)


@router.get(
    "/parsed-documents/{parsed_document_id}/segments",
    response_model=DocumentSegmentPageRead,
)
def read_parsed_document_segments(
    parsed_document_id: UUID,
    session: SessionDep,
    offset: int = 0,
    limit: int = 50,
) -> DocumentSegmentPageRead:
    current_user = require_current_user(session)
    parsed_document = session.exec(
        select(ParsedDocument).where(
            ParsedDocument.id == parsed_document_id,
            ParsedDocument.owner_user_id == current_user.id,
        )
    ).first()
    if parsed_document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parsed document not found",
        )

    bounded_limit = max(1, min(limit, 200))
    normalized_offset = max(0, offset)
    total = session.exec(
        select(func.count(DocumentSegment.id)).where(
            DocumentSegment.parsed_document_id == parsed_document.id
        )
    ).one()
    segments = session.exec(
        select(DocumentSegment)
        .where(DocumentSegment.parsed_document_id == parsed_document.id)
        .order_by(DocumentSegment.sequence_index)
        .offset(normalized_offset)
        .limit(bounded_limit)
    ).all()

    return DocumentSegmentPageRead(
        items=[to_segment_read(segment) for segment in segments],
        total=total,
        offset=normalized_offset,
        limit=bounded_limit,
    )


def make_document_parse_service(*, session: Session, settings: Settings) -> DocumentParseService:
    return DocumentParseService(
        session=session,
        upload_storage=LocalFileStorage(settings.upload_storage_dir),
        document_parse_enabled=settings.document_parse_enabled,
        max_parse_bytes=settings.document_parse_max_bytes,
        max_parse_pages=settings.document_parse_max_pages,
        allowed_content_types=set(settings.document_parse_allowed_content_types),
        allowed_extensions=set(settings.document_parse_allowed_extensions),
    )


def require_current_user(session: Session):
    try:
        return get_current_user(session)
    except CurrentUserUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Current user is unavailable",
        ) from exc


def get_owned_upload(*, session: Session, upload_id: UUID, owner_user_id: UUID) -> UploadedFile:
    upload = session.exec(
        select(UploadedFile).where(
            UploadedFile.id == upload_id,
            UploadedFile.owner_user_id == owner_user_id,
            UploadedFile.deleted_at.is_(None),
        )
    ).first()
    if upload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")

    return upload


def to_uploaded_file_parse_info(uploaded_file: UploadedFile) -> UploadedFileParseInfo:
    return UploadedFileParseInfo(
        id=uploaded_file.id,
        original_filename=uploaded_file.original_filename,
        content_type=uploaded_file.content_type,
        byte_size=uploaded_file.byte_size,
        status=uploaded_file.status,
    )


def to_parsed_document_read(
    parsed_document: ParsedDocument,
    *,
    segment_count: int,
) -> ParsedDocumentRead:
    return ParsedDocumentRead(
        id=parsed_document.id,
        uploaded_file_id=parsed_document.uploaded_file_id,
        parse_job_id=parsed_document.parse_job_id,
        owner_user_id=parsed_document.owner_user_id,
        source_checksum_sha256=parsed_document.source_checksum_sha256,
        markdown_storage_key=parsed_document.markdown_storage_key,
        text_storage_key=parsed_document.text_storage_key,
        docling_json_storage_key=parsed_document.docling_json_storage_key,
        title=parsed_document.title,
        page_count=parsed_document.page_count,
        metadata=parsed_document.metadata_json,
        segment_count=segment_count,
        created_at=parsed_document.created_at,
    )


def to_segment_read(segment: DocumentSegment) -> DocumentSegmentRead:
    return DocumentSegmentRead(
        id=segment.id,
        parsed_document_id=segment.parsed_document_id,
        owner_user_id=segment.owner_user_id,
        sequence_index=segment.sequence_index,
        segment_type=segment.segment_type,
        page_no=segment.page_no,
        heading_path=segment.heading_path,
        text=segment.text,
        metadata=segment.metadata_json,
        created_at=segment.created_at,
    )
