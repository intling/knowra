from sqlmodel import SQLModel

from app.models.chat_quota import ChatUsage, UserChatLimit
from app.models.document_chunking import DocumentChunk, DocumentChunkJob
from app.models.document_embedding import DocumentEmbedding, DocumentEmbeddingJob
from app.models.document_parsing import DocumentParseJob, DocumentSegment, ParsedDocument
from app.models.model_configuration import ModelBinding, ModelProfile
from app.models.uploaded_file import UploadedFile
from app.models.user import User, UserCredential, UserSession

# Import model modules here so Alembic can discover SQLModel metadata.
metadata = SQLModel.metadata

__all__ = [
    "ModelBinding",
    "ModelProfile",
    "ChatUsage",
    "DocumentChunk",
    "DocumentChunkJob",
    "DocumentEmbedding",
    "DocumentEmbeddingJob",
    "DocumentParseJob",
    "DocumentSegment",
    "ParsedDocument",
    "UploadedFile",
    "User",
    "UserChatLimit",
    "UserCredential",
    "UserSession",
    "metadata",
]
