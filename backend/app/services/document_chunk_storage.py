from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID


class ChunkArtifactStorageError(Exception):
    pass


@dataclass(frozen=True)
class StoredChunkTexts:
    text: str | None
    text_storage_key: str | None
    contextualized_text: str | None
    contextualized_text_storage_key: str | None


class ChunkArtifactStorage:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)

    def path_for(self, storage_key: str) -> Path:
        path_parts = PurePosixPath(storage_key).parts
        if not path_parts or any(part in {"", ".", ".."} for part in path_parts):
            raise ChunkArtifactStorageError("Invalid chunk artifact storage key")

        return self.root_dir.joinpath(*path_parts)

    def save_texts(
        self,
        *,
        owner_user_id: UUID,
        parsed_document_id: UUID,
        chunk_job_id: UUID,
        sequence_index: int,
        text: str,
        contextualized_text: str,
        inline_text_max_bytes: int,
    ) -> StoredChunkTexts:
        text_value, text_key = self._store_one(
            owner_user_id=owner_user_id,
            parsed_document_id=parsed_document_id,
            chunk_job_id=chunk_job_id,
            sequence_index=sequence_index,
            suffix="text",
            content=text,
            inline_text_max_bytes=inline_text_max_bytes,
        )
        contextualized_value, contextualized_key = self._store_one(
            owner_user_id=owner_user_id,
            parsed_document_id=parsed_document_id,
            chunk_job_id=chunk_job_id,
            sequence_index=sequence_index,
            suffix="contextualized",
            content=contextualized_text,
            inline_text_max_bytes=inline_text_max_bytes,
        )
        return StoredChunkTexts(
            text=text_value,
            text_storage_key=text_key,
            contextualized_text=contextualized_value,
            contextualized_text_storage_key=contextualized_key,
        )

    def _store_one(
        self,
        *,
        owner_user_id: UUID,
        parsed_document_id: UUID,
        chunk_job_id: UUID,
        sequence_index: int,
        suffix: str,
        content: str,
        inline_text_max_bytes: int,
    ) -> tuple[str | None, str | None]:
        if len(content.encode("utf-8")) <= inline_text_max_bytes:
            return content, None

        storage_key = (
            f"chunks/{owner_user_id}/{parsed_document_id}/{chunk_job_id}/"
            f"{sequence_index:06d}_{suffix}.txt"
        )
        path = self.path_for(storage_key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise ChunkArtifactStorageError("Failed to write chunk artifact") from exc

        return None, storage_key
