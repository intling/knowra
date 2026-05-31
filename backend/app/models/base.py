from sqlmodel import SQLModel

from app.models.uploaded_file import UploadedFile
from app.models.user import User

# Import model modules here so Alembic can discover SQLModel metadata.
metadata = SQLModel.metadata

__all__ = ["UploadedFile", "User", "metadata"]
