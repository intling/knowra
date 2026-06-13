# 本文件验证解析适配器返回结果的边界。
# 可持久化 payload 用于落盘，transient DoclingDocument 只在内存中传给分块流程。

from importlib import import_module

from tests.document_parsing_helpers import write_minimal_pdf, write_text_fixture


class FakeDoclingDocument:
    # 模拟 DoclingDocument 的导出接口。
    # 测试用它区分可持久化 markdown/text/json 与不可持久化的内存对象。
    pages = [object()]
    title = "Parsed Fixture"

    # 导出 Markdown payload，用于验证 persistent_payload.markdown 的内容来源。
    def export_to_markdown(self):
        return "# Parsed Fixture\n\nBody"

    # 导出纯文本 payload，用于验证 persistent_payload.text 的内容来源。
    def export_to_text(self):
        return "Parsed Fixture\nBody"

    # 导出可 JSON 持久化的 Docling 字典，用于验证 docling_json 落盘内容。
    def export_to_dict(self):
        return {"name": "Parsed Fixture", "texts": [{"text": "Body"}]}


class FakeConverter:
    # 持有稳定 fake DoclingDocument。
    # 便于断言 parser 返回的 transient 对象与 converter 产物是同一个实例。
    def __init__(self) -> None:
        self.document = FakeDoclingDocument()

    # 模拟 Docling converter 成功解析任意输入文件，并返回同一个内存文档。
    def convert(self, *_args, **_kwargs):
        return self.document


# PDF/Docling 解析成功时，适配器应同时返回可落盘 payload 和 transient DoclingDocument。
# 测试确认 transient 对象就是 converter 产出的同一个实例，供后续自动分块复用。
def test_docling_parser_adapter_returns_persistent_payload_and_transient_document(tmp_path) -> None:
    parser = import_module("app.services.document_parser")
    path = write_minimal_pdf(tmp_path / "fixture.pdf")
    converter = FakeConverter()
    adapter = parser.DoclingParserAdapter(
        ocr_enabled=False,
        max_pages=100,
        docling_cache_dir=tmp_path / "cache",
        converter=converter,
    )

    result = adapter.parse(path, document_format=parser.DocumentFormat.PDF)

    assert result.persistent_payload.markdown.startswith("# Parsed Fixture")
    assert result.persistent_payload.text == "Parsed Fixture\nBody"
    assert result.persistent_payload.docling_json["name"] == "Parsed Fixture"
    assert result.transient_docling_document is not None
    assert result.transient_docling_document is converter.document


# TXT 兜底解析没有原生 DoclingDocument。
# 测试确认它仍返回文本 payload，并用明确原因标识 transient 文档不可用。
def test_txt_parser_result_has_clear_missing_transient_docling_document_semantics(tmp_path) -> None:
    parser = import_module("app.services.document_parser")
    path = write_text_fixture(tmp_path / "fixture.txt", "Fallback text\n")
    adapter = parser.DoclingParserAdapter(
        ocr_enabled=False,
        max_pages=100,
        docling_cache_dir=tmp_path / "cache",
    )

    result = adapter.parse(path, document_format=parser.DocumentFormat.TXT)

    assert result.persistent_payload.text == "Fallback text\n"
    assert result.transient_docling_document is None
    assert result.transient_missing_reason == "native_docling_document_unavailable"


# 保存解析结果时只能持久化 payload。
# 测试确认 transient 对象或其类名不会写进 docling.json，避免污染存储契约。
def test_transient_docling_document_is_not_part_of_persistent_payload(tmp_path) -> None:
    parser = import_module("app.services.document_parser")
    storage_module = import_module("app.services.document_parse_storage")
    path = write_minimal_pdf(tmp_path / "fixture.pdf")
    adapter = parser.DoclingParserAdapter(
        ocr_enabled=False,
        max_pages=100,
        docling_cache_dir=tmp_path / "cache",
        converter=FakeConverter(),
    )
    result = adapter.parse(path, document_format=parser.DocumentFormat.PDF)

    storage = storage_module.ParsedArtifactStorage(tmp_path / "parsed")
    keys = storage.save(
        owner_user_id=__import__("uuid").uuid4(),
        uploaded_file_id=__import__("uuid").uuid4(),
        parse_job_id=__import__("uuid").uuid4(),
        payload=result.persistent_payload,
    )

    stored_json = storage.path_for(keys.docling_json_storage_key).read_text(encoding="utf-8")
    assert "transient_docling_document" not in stored_json
    assert "FakeDoclingDocument" not in stored_json
