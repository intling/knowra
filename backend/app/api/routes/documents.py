from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlmodel import Session

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.models.document import Document
from app.models.uploaded_file import UploadedFile
from app.schemas.document import DocumentChunkRead, DocumentCreate, DocumentRead, SourceFileRead
from app.services.document_processing import (
    DocumentAlreadyExistsError,
    DocumentProcessingService,
    DocumentProcessingServiceError,
    UnsupportedDocumentForProcessingError,
    UploadedFileNotFoundError,
    UploadedFileNotStoredError,
)
from app.services.uploads import LocalFileStorage
from app.services.users import CurrentUserUnavailableError, get_current_user

router = APIRouter(prefix="/documents", tags=["documents"])
SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
def create_document(
    payload: DocumentCreate,
    session: SessionDep,
    settings: SettingsDep,
):
    try:
        current_user = get_current_user(session)
    except CurrentUserUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Current user is unavailable",
        ) from exc

    service = build_service(session=session, settings=settings)
    try:
        document = service.create_document(
            current_user=current_user,
            uploaded_file_id=payload.uploaded_file_id,
        )
    except UploadedFileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Uploaded file not found",
        ) from exc
    except UploadedFileNotStoredError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DocumentAlreadyExistsError as exc:
        existing_document = document_to_read(session=session, document=exc.existing_document)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=jsonable_encoder({"existing_document": existing_document}),
        )
    except UnsupportedDocumentForProcessingError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc
    except DocumentProcessingServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process document",
        ) from exc

    return document_to_read(session=session, document=document)


@router.get("", response_model=list[DocumentRead])
def list_documents(session: SessionDep, settings: SettingsDep) -> list[DocumentRead]:
    current_user = resolve_current_user(session)
    service = build_service(session=session, settings=settings)
    return [
        document_to_read(session=session, document=document)
        for document in service.list_documents(current_user=current_user)
    ]


@router.get("/{document_id}", response_model=DocumentRead)
def read_document(
    document_id: UUID,
    session: SessionDep,
    settings: SettingsDep,
) -> DocumentRead:
    current_user = resolve_current_user(session)
    service = build_service(session=session, settings=settings)
    document = service.get_document(current_user=current_user, document_id=document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    return document_to_read(session=session, document=document)


@router.get("/{document_id}/chunks", response_model=list[DocumentChunkRead])
def list_document_chunks(
    document_id: UUID,
    session: SessionDep,
    settings: SettingsDep,
) -> list[DocumentChunkRead]:
    current_user = resolve_current_user(session)
    service = build_service(session=session, settings=settings)
    chunks = service.list_chunks(current_user=current_user, document_id=document_id)
    if chunks is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    return [DocumentChunkRead.model_validate(chunk, from_attributes=True) for chunk in chunks]


def build_service(*, session: Session, settings: Settings) -> DocumentProcessingService:
    return DocumentProcessingService(
        session=session,
        storage=LocalFileStorage(settings.upload_storage_dir),
    )


def resolve_current_user(session: Session):
    try:
        return get_current_user(session)
    except CurrentUserUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Current user is unavailable",
        ) from exc


def document_to_read(*, session: Session, document: Document) -> DocumentRead:
    source_file = session.get(UploadedFile, document.uploaded_file_id)
    source_file_read = (
        SourceFileRead.model_validate(source_file, from_attributes=True)
        if source_file is not None
        else None
    )
    return DocumentRead(
        id=document.id,
        owner_user_id=document.owner_user_id,
        uploaded_file_id=document.uploaded_file_id,
        title=document.title,
        source_content_type=document.source_content_type,
        parser_name=document.parser_name,
        parser_version=document.parser_version,
        chunker_name=document.chunker_name,
        chunker_version=document.chunker_version,
        tokenizer_name=document.tokenizer_name,
        tokenizer_version=document.tokenizer_version,
        status=document.status,
        chunk_count=document.chunk_count,
        total_chars=document.total_chars,
        content_sha256=document.content_sha256,
        metadata_json=document.metadata_json,
        error_message=document.error_message,
        deleted_at=document.deleted_at,
        created_at=document.created_at,
        updated_at=document.updated_at,
        source_file=source_file_read,
    )
