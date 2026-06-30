from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile


class DocumentParseError(Exception):
    pass


class UnsupportedDocumentFormatError(DocumentParseError):
    pass


class DocumentFormat(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    MARKDOWN = "markdown"
    TXT = "txt"


@dataclass(frozen=True)
class ParsedSegmentPayload:
    sequence_index: int
    segment_type: str
    text: str
    page_no: int | None = None
    heading_path: list[str] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedDocumentPayload:
    markdown: str
    text: str
    docling_json: dict[str, Any]
    title: str | None = None
    page_count: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    segments: list[ParsedSegmentPayload] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedDocumentResult:
    persistent_payload: ParsedDocumentPayload
    transient_docling_document: Any | None = None
    transient_missing_reason: str | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.persistent_payload, name)


def ensure_parsed_payload_has_text_content(payload: ParsedDocumentPayload) -> None:
    text_candidates = [payload.markdown, payload.text]
    text_candidates.extend(segment.text for segment in payload.segments)
    if not any(candidate.strip() for candidate in text_candidates):
        raise DocumentParseError("Parsed document has no text content")


@dataclass(frozen=True)
class DocumentFormatPolicy:
    allowed_content_types: set[str]
    allowed_extensions: set[str]

    def validate(
        self,
        path: str | Path,
        *,
        original_filename: str,
        content_type: str | None,
    ) -> DocumentFormat:
        candidate = self._candidate_format(original_filename, content_type)
        extension = Path(original_filename).suffix.lower()
        content_type_allowed = content_type in self.allowed_content_types if content_type else False
        extension_allowed = extension in self.allowed_extensions
        if candidate is None or not (content_type_allowed or extension_allowed):
            raise UnsupportedDocumentFormatError("Unsupported document format")

        file_path = Path(path)
        if candidate == DocumentFormat.PDF:
            self._validate_pdf(file_path)
        elif candidate == DocumentFormat.DOCX:
            self._validate_ooxml(file_path, "word/document.xml")
        elif candidate == DocumentFormat.PPTX:
            self._validate_ooxml(file_path, "ppt/presentation.xml")
        elif candidate in {DocumentFormat.MARKDOWN, DocumentFormat.TXT}:
            self._validate_text(file_path)

        return candidate

    @staticmethod
    def _candidate_format(
        original_filename: str,
        content_type: str | None,
    ) -> DocumentFormat | None:
        extension = Path(original_filename).suffix.lower()
        if content_type == "application/pdf" or extension == ".pdf":
            return DocumentFormat.PDF
        if (
            content_type
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            or extension == ".docx"
        ):
            return DocumentFormat.DOCX
        if (
            content_type
            == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            or extension == ".pptx"
        ):
            return DocumentFormat.PPTX
        if content_type == "text/markdown" or extension in {".md", ".markdown"}:
            return DocumentFormat.MARKDOWN
        if content_type == "text/plain" or extension == ".txt":
            return DocumentFormat.TXT

        return None

    @staticmethod
    def _validate_pdf(path: Path) -> None:
        if not path.read_bytes()[:5] == b"%PDF-":
            raise UnsupportedDocumentFormatError("PDF header does not match")

    @staticmethod
    def _validate_ooxml(path: Path, required_member: str) -> None:
        try:
            with ZipFile(path) as archive:
                names = set(archive.namelist())
        except (BadZipFile, OSError) as exc:
            raise UnsupportedDocumentFormatError("OOXML container is invalid") from exc

        if "[Content_Types].xml" not in names or required_member not in names:
            raise UnsupportedDocumentFormatError("OOXML document structure does not match")

    @staticmethod
    def _validate_text(path: Path) -> None:
        try:
            sample = path.read_bytes()[:8192]
            sample.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UnsupportedDocumentFormatError("Text sample is not readable") from exc

        if b"\x00" in sample:
            raise UnsupportedDocumentFormatError("Text sample contains binary data")


class DoclingParserAdapter:
    def __init__(
        self,
        *,
        ocr_enabled: bool,
        max_pages: int,
        docling_cache_dir: str | Path,
        converter: object | None = None,
    ) -> None:
        self.ocr_enabled = ocr_enabled
        self.max_pages = max_pages
        self.docling_cache_dir = Path(docling_cache_dir)
        self.converter = converter

    def parse(self, path: str | Path, *, document_format: DocumentFormat) -> ParsedDocumentResult:
        file_path = Path(path)
        if document_format in {DocumentFormat.TXT, DocumentFormat.MARKDOWN}:
            return self._parse_text(file_path, document_format=document_format)

        converter = self.converter or self._create_converter()
        try:
            result = converter.convert(file_path, max_num_pages=self.max_pages)
        except Exception as exc:
            raise DocumentParseError(str(exc)) from exc

        return self._normalize_docling_result(result)

    def _parse_text(
        self,
        path: Path,
        *,
        document_format: DocumentFormat,
    ) -> ParsedDocumentResult:
        text = path.read_text(encoding="utf-8")
        source_format = document_format.value
        payload = ParsedDocumentPayload(
            markdown=text,
            text=text,
            docling_json={
                "source_format": source_format,
                "content": text,
            },
            page_count=1,
            metadata={"source_format": source_format},
            segments=[
                ParsedSegmentPayload(
                    sequence_index=0,
                    segment_type="paragraph",
                    page_no=1,
                    text=text,
                    metadata={"source_format": source_format},
                )
            ],
        )
        ensure_parsed_payload_has_text_content(payload)
        return ParsedDocumentResult(
            persistent_payload=payload,
            transient_docling_document=None,
            transient_missing_reason="native_docling_document_unavailable",
        )

    def _create_converter(self) -> object:
        try:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption
        except ImportError as exc:
            raise DocumentParseError("Docling is not installed") from exc

        pdf_options = PdfPipelineOptions()
        pdf_options.do_ocr = self.ocr_enabled
        if self._docling_cache_dir_has_artifacts():
            pdf_options.artifacts_path = self.docling_cache_dir

        return DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
            }
        )

    def _docling_cache_dir_has_artifacts(self) -> bool:
        try:
            return self.docling_cache_dir.is_dir() and any(self.docling_cache_dir.iterdir())
        except OSError:
            return False

    @staticmethod
    def _normalize_docling_result(result: object) -> ParsedDocumentResult:
        document = getattr(result, "document", result)
        markdown = call_optional(document, "export_to_markdown") or ""
        text = call_optional(document, "export_to_text") or markdown
        docling_json = call_optional(document, "export_to_dict") or {"content": text}
        pages = getattr(document, "pages", None)
        page_count = len(pages) if pages is not None else None
        title = getattr(document, "title", None)

        if not text:
            text = markdown

        payload = ParsedDocumentPayload(
            markdown=markdown,
            text=text,
            docling_json=docling_json,
            title=title,
            page_count=page_count,
            metadata={"source_format": "docling"},
            segments=[
                ParsedSegmentPayload(
                    sequence_index=0,
                    segment_type="document",
                    page_no=1 if page_count else None,
                    text=text,
                    metadata={"source_format": "docling"},
                )
            ],
        )
        ensure_parsed_payload_has_text_content(payload)
        return ParsedDocumentResult(
            persistent_payload=payload,
            transient_docling_document=document,
        )


def call_optional(target: object, name: str) -> Any | None:
    method = getattr(target, name, None)
    if callable(method):
        return method()

    return None
