from importlib import import_module
from uuid import uuid4

import pytest

from tests.document_parsing_helpers import (
    ParsedPayloadFactory,
    write_minimal_docx,
    write_minimal_pdf,
    write_minimal_pptx,
    write_text_fixture,
)


def get_parser_module():
    return import_module("app.services.document_parser")


def get_storage_module():
    return import_module("app.services.document_parse_storage")


def make_policy(parser):
    return parser.DocumentFormatPolicy(
        allowed_content_types={
            "application/pdf",
            "text/markdown",
            "text/plain",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
        allowed_extensions={".docx", ".md", ".markdown", ".pdf", ".pptx", ".txt"},
    )


@pytest.mark.parametrize(
    ("writer", "filename", "content_type", "expected_format"),
    [
        (write_minimal_pdf, "notes.pdf", "application/pdf", "PDF"),
        (
            write_minimal_docx,
            "notes.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "DOCX",
        ),
        (
            write_minimal_pptx,
            "slides.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "PPTX",
        ),
        (write_text_fixture, "notes.md", "text/markdown", "MARKDOWN"),
        (write_text_fixture, "notes.txt", "text/plain", "TXT"),
    ],
)
# 测试格式策略能识别首版支持的 PDF/DOCX/PPTX/Markdown/TXT。
def test_document_format_policy_accepts_supported_formats(
    tmp_path,
    writer,
    filename: str,
    content_type: str,
    expected_format: str,
) -> None:
    parser = get_parser_module()
    path = writer(tmp_path / filename)
    policy = make_policy(parser)

    detected = policy.validate(path, original_filename=filename, content_type=content_type)

    assert detected == getattr(parser.DocumentFormat, expected_format)


@pytest.mark.parametrize(
    ("content", "filename", "content_type"),
    [
        (b"not a pdf", "fake.pdf", "application/pdf"),
        (
            b"not a zip",
            "fake.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            b"not a zip",
            "fake.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
        (b"\x00\x01\x02\x03", "binary.txt", "text/plain"),
    ],
)
# 测试伪造或结构不匹配的文件会在进入 Docling 前被拒绝。
def test_document_format_policy_rejects_spoofed_or_unreadable_files(
    tmp_path,
    content: bytes,
    filename: str,
    content_type: str,
) -> None:
    parser = get_parser_module()
    path = tmp_path / filename
    path.write_bytes(content)
    policy = make_policy(parser)

    with pytest.raises(parser.UnsupportedDocumentFormatError):
        policy.validate(path, original_filename=filename, content_type=content_type)


# 测试 TXT 在 Docling 不稳定支持时仍由同一适配器 facade 生成统一产物契约。
def test_docling_parser_adapter_generates_txt_fallback_payload(tmp_path) -> None:
    parser = get_parser_module()
    path = write_text_fixture(tmp_path / "notes.txt", "Line one\nLine two\n")
    adapter = parser.DoclingParserAdapter(
        ocr_enabled=False,
        max_pages=100,
        docling_cache_dir=tmp_path / "cache",
    )

    payload = adapter.parse(path, document_format=parser.DocumentFormat.TXT)

    assert payload.markdown == "Line one\nLine two\n"
    assert payload.text == "Line one\nLine two\n"
    assert payload.docling_json["source_format"] == "txt"
    assert payload.page_count == 1
    assert payload.segments[0].sequence_index == 0
    assert payload.segments[0].text == "Line one\nLine two\n"


# 测试适配器把第三方转换异常转成项目内可诊断错误。
def test_docling_parser_adapter_converts_sdk_exceptions(tmp_path) -> None:
    parser = get_parser_module()
    path = write_minimal_pdf(tmp_path / "notes.pdf")

    class BrokenConverter:
        def convert(self, *_args, **_kwargs):
            raise RuntimeError("converter failed")

    adapter = parser.DoclingParserAdapter(
        ocr_enabled=False,
        max_pages=100,
        docling_cache_dir=tmp_path / "cache",
        converter=BrokenConverter(),
    )

    with pytest.raises(parser.DocumentParseError, match="converter failed"):
        adapter.parse(path, document_format=parser.DocumentFormat.PDF)


def test_docling_parser_adapter_passes_max_pages_to_converter(tmp_path) -> None:
    parser = get_parser_module()
    path = write_minimal_pdf(tmp_path / "notes.pdf")
    captured = {}

    class FakeDocument:
        pages = [object()]

        def export_to_markdown(self):
            return "# Parsed\n"

        def export_to_text(self):
            return "Parsed\n"

        def export_to_dict(self):
            return {"content": "Parsed"}

    class CapturingConverter:
        def convert(self, *_args, **kwargs):
            captured.update(kwargs)
            return FakeDocument()

    adapter = parser.DoclingParserAdapter(
        ocr_enabled=False,
        max_pages=3,
        docling_cache_dir=tmp_path / "cache",
        converter=CapturingConverter(),
    )

    adapter.parse(path, document_format=parser.DocumentFormat.PDF)

    assert captured["max_num_pages"] == 3


def test_docling_parser_adapter_configures_pdf_converter_options(monkeypatch, tmp_path) -> None:
    parser = get_parser_module()
    cache_dir = tmp_path / "docling-cache"
    cache_dir.joinpath("docling-project--docling-layout-heron").mkdir(parents=True)
    captured = {}

    import docling.document_converter as document_converter
    from docling.datamodel.base_models import InputFormat

    class FakeDocumentConverter:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

    monkeypatch.setattr(document_converter, "DocumentConverter", FakeDocumentConverter)

    adapter = parser.DoclingParserAdapter(
        ocr_enabled=False,
        max_pages=7,
        docling_cache_dir=cache_dir,
    )

    converter = adapter._create_converter()

    assert isinstance(converter, FakeDocumentConverter)
    pdf_options = captured["kwargs"]["format_options"][InputFormat.PDF].pipeline_options
    assert pdf_options.do_ocr is False
    assert pdf_options.artifacts_path == cache_dir


# 测试 Docling 成功返回但未提取到正文时，适配器会转成解析失败。
def test_docling_parser_adapter_rejects_empty_extracted_content(tmp_path) -> None:
    parser = get_parser_module()
    path = write_minimal_pdf(tmp_path / "blank.pdf")

    class EmptyDocument:
        pages = []

        def export_to_markdown(self):
            return ""

        def export_to_text(self):
            return ""

        def export_to_dict(self):
            return {"content": ""}

    class EmptyConverter:
        def convert(self, *_args, **_kwargs):
            return EmptyDocument()

    adapter = parser.DoclingParserAdapter(
        ocr_enabled=False,
        max_pages=100,
        docling_cache_dir=tmp_path / "cache",
        converter=EmptyConverter(),
    )

    with pytest.raises(parser.DocumentParseError, match="no text content"):
        adapter.parse(path, document_format=parser.DocumentFormat.PDF)


# 测试解析产物存储只写 Markdown/Text/JSON，不保存页面图或截图类派生图片。
def test_parsed_artifact_storage_writes_only_text_and_json_artifacts(tmp_path) -> None:
    storage_module = get_storage_module()
    payload = ParsedPayloadFactory().make()
    owner_user_id = uuid4()
    uploaded_file_id = uuid4()
    parse_job_id = uuid4()
    storage = storage_module.ParsedArtifactStorage(root_dir=tmp_path)

    keys = storage.save(
        owner_user_id=owner_user_id,
        uploaded_file_id=uploaded_file_id,
        parse_job_id=parse_job_id,
        payload=payload,
    )

    assert keys.markdown_storage_key.endswith("/content.md")
    assert keys.text_storage_key.endswith("/content.txt")
    assert keys.docling_json_storage_key.endswith("/docling.json")
    assert (
        tmp_path.joinpath(*keys.markdown_storage_key.split("/")).read_text(encoding="utf-8")
        == payload.markdown
    )
    assert not any(
        path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} for path in tmp_path.rglob("*")
    )
