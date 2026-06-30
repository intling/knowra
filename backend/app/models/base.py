from sqlmodel import SQLModel

from app.models.document_parsing import DocumentParseJob, DocumentSegment, ParsedDocument
from app.models.uploaded_file import UploadedFile
from app.models.user import User

# Import model modules here so Alembic can discover SQLModel metadata.
metadata = SQLModel.metadata

__all__ = [
    "DocumentParseJob",
    "DocumentSegment",
    "ParsedDocument",
    "UploadedFile",
    "User",
    "metadata",
]
