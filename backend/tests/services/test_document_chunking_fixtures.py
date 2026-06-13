# 本文件验证文档分块测试 fixture 的质量。
# 样本文本应足够小、覆盖标题/正文，并能生成无需 OCR 的内存 DoclingDocument。

from tests.document_chunking_helpers import (
    MARKDOWN_CHUNKING_FIXTURE,
    TXT_CHUNKING_FIXTURE,
    make_minimal_docling_document,
)


# Markdown/TXT fixture 应包含同一课程标题和正文，且体积低于内联阈值。
# 这些样本供存储和解析链路测试稳定复用。
def test_markdown_and_txt_chunking_fixtures_are_small_text_samples() -> None:
    assert "# Course Notes" in MARKDOWN_CHUNKING_FIXTURE
    assert "Course Notes" in TXT_CHUNKING_FIXTURE
    assert "Semantic retrieval" in MARKDOWN_CHUNKING_FIXTURE
    assert len(MARKDOWN_CHUNKING_FIXTURE.encode("utf-8")) < 2048
    assert len(TXT_CHUNKING_FIXTURE.encode("utf-8")) < 2048


# 最小 DoclingDocument fixture 应能导出标题和正文。
# 这证明服务测试可以用内存文档覆盖 Docling 分块入口。
def test_minimal_docling_document_fixture_exports_text_without_ocr_or_large_files() -> None:
    document = make_minimal_docling_document()

    assert document.name == "chunking-fixture"
    assert "Course Notes" in document.export_to_text()
    assert "Semantic retrieval" in document.export_to_text()
