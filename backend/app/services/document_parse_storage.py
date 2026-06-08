import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID

from app.services.document_parser import ParsedDocumentPayload


class ParsedArtifactStorageError(Exception):
    pass


@dataclass(frozen=True)
class ParsedArtifactKeys:
    markdown_storage_key: str
    text_storage_key: str
    docling_json_storage_key: str


class ParsedArtifactStorage:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)

    def path_for(self, storage_key: str) -> Path:
        path_parts = PurePosixPath(storage_key).parts
        if not path_parts or any(part in {"", ".", ".."} for part in path_parts):
            raise ParsedArtifactStorageError("Invalid parsed artifact storage key")

        return self.root_dir.joinpath(*path_parts)

    def save(
        self,
        *,
        owner_user_id: UUID,
        uploaded_file_id: UUID,
        parse_job_id: UUID,
        payload: ParsedDocumentPayload,
    ) -> ParsedArtifactKeys:
        base_key = f"parsed/{owner_user_id}/{uploaded_file_id}/{parse_job_id}"
        markdown_key = f"{base_key}/content.md"
        text_key = f"{base_key}/content.txt"
        json_key = f"{base_key}/docling.json"

        try:
            self._write_text(markdown_key, payload.markdown)
            self._write_text(text_key, payload.text)
            self._write_text(json_key, json.dumps(payload.docling_json, ensure_ascii=False))
        except OSError as exc:
            raise ParsedArtifactStorageError("Failed to write parsed artifacts") from exc

        return ParsedArtifactKeys(
            markdown_storage_key=markdown_key,
            text_storage_key=text_key,
            docling_json_storage_key=json_key,
        )

    def _write_text(self, storage_key: str, content: str) -> None:
        path = self.path_for(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
