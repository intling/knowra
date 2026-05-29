from importlib import import_module

import pytest

# 本文件验证文档解析、存储读取和分块阶段的主要失败路径会给出可控错误。


def get_processing_module():
    return import_module("app.services.document_processing")


def make_blank_pdf_bytes() -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (b"<< /Type /Page /Parent 2 0 R /Resources << >> /MediaBox [0 0 612 792] >>"),
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(pdf)


# 测试解析注册表会拒绝不支持的文件类型，而不是交给任意解析器处理。
def test_registry_rejects_unsupported_document_types() -> None:
    processing = get_processing_module()
    registry = processing.create_default_parser_registry()

    with pytest.raises(processing.UnsupportedDocumentTypeError, match="Unsupported"):
        registry.parse(
            filename="archive.zip",
            content_type="application/zip",
            content=b"not a supported document",
        )


# 测试文本解析器遇到非 UTF-8 内容时返回明确的解码失败错误。
def test_text_parser_reports_utf8_decode_failures() -> None:
    processing = get_processing_module()
    registry = processing.create_default_parser_registry()

    with pytest.raises(processing.DocumentParseError, match="UTF-8"):
        registry.parse(
            filename="broken.txt",
            content_type="text/plain",
            content=b"\xff\xfe\xfd",
        )


# 测试 PDF 没有可抽取文本时会提示需要 OCR 或缺少 extractable text。
def test_pdf_parser_reports_scanned_or_empty_pdf_without_extractable_text() -> None:
    processing = get_processing_module()
    registry = processing.create_default_parser_registry()

    with pytest.raises(processing.DocumentParseError, match="OCR|extractable text"):
        registry.parse(
            filename="scan.pdf",
            content_type="application/pdf",
            content=make_blank_pdf_bytes(),
        )


# 测试上传记录指向的原始文件缺失时，存储层会抛出可识别的存储错误。
def test_storage_open_reports_missing_original_files(tmp_path) -> None:
    uploads = import_module("app.services.uploads")
    storage = uploads.LocalFileStorage(root_dir=tmp_path)

    with (
        pytest.raises(uploads.UploadStorageError, match="missing|not found"),
        storage.open("uploads/user-id/upload-id/original.txt"),
    ):
        pass


# 测试分块器拒绝空解析结果，避免生成无意义的空文档分块。
def test_chunker_rejects_empty_parsed_documents() -> None:
    processing = get_processing_module()
    parsed = processing.ParsedDocument(
        text="",
        segments=[],
        metadata_json={},
        parser_name="test-parser",
        parser_version="0",
    )
    chunker = processing.BpeChunker(tokenizer=processing.BpeTokenizer(), max_tokens=32)

    with pytest.raises(processing.DocumentParseError, match="empty"):
        chunker.chunk(parsed)


# 测试解析器内部抛出未知异常时，注册表会包装为统一的 DocumentParseError。
def test_parser_registry_wraps_unexpected_parser_exceptions() -> None:
    processing = get_processing_module()

    class ExplodingParser:
        name = "exploding"
        version = "test"
        supported_content_types = {"text/plain"}
        supported_extensions = {".txt"}

        def parse(self, *, filename: str, content_type: str | None, content: bytes):
            raise RuntimeError("parser exploded")

    registry = processing.ParserRegistry([ExplodingParser()])

    with pytest.raises(processing.DocumentParseError, match="Failed to parse"):
        registry.parse(filename="notes.txt", content_type="text/plain", content=b"notes")
