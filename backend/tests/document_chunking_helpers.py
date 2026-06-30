# 本文件提供文档分块测试的可复用 fixture。
# 这些 fixture 覆盖内存 DoclingDocument、临时分块数据库、解析结果和稳定 storage key，
# 让测试能验证分块链路行为，而不依赖 OCR、大文件或网络下载。

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.document_parsing import DocumentParseJob, DocumentSegment, ParsedDocument
from app.models.uploaded_file import UploadedFile
from app.models.user import User
from tests.document_parsing_helpers import make_uploaded_file, make_user

MARKDOWN_CHUNKING_FIXTURE = """# Course Notes

## Retrieval

Semantic retrieval should preserve source structure and stable ordering.
"""

TXT_CHUNKING_FIXTURE = (
    "Course Notes\n\n"
    "Retrieval\n\n"
    "Semantic retrieval should preserve source structure and stable ordering.\n"
)


@dataclass(frozen=True)
class ChunkFixture:
    # 模拟分块器输出的项目内标准 chunk。
    # 服务测试用它验证正文、上下文化文本、token、标题、页码和来源元数据的落库映射。
    text: str
    contextualized_text: str
    token_count: int = 12
    heading_path: list[str] | None = None
    page_numbers: list[int] | None = None
    chunk_type: str = "text"
    source_segment_indices: list[int] | None = None
    metadata: dict | None = None


# 生成带标题、章节和正文的内存 DoclingDocument。
# 适配器与服务测试用它验证分块入口可以直接消费解析阶段的 transient 文档。
def make_minimal_docling_document():
    from docling_core.types.doc.document import DoclingDocument
    from docling_core.types.doc.labels import DocItemLabel

    document = DoclingDocument(name="chunking-fixture")
    document.add_title("Course Notes")
    document.add_heading("Retrieval", level=1)
    document.add_text(
        label=DocItemLabel.PARAGRAPH,
        text="Semantic retrieval should preserve source structure and stable ordering.",
    )
    return document


@contextmanager
# 创建包含分块相关模型的内存 SQLite session。
# 模型和服务测试用它验证建表、外键和 chunk 落库逻辑，无需真实数据库。
def chunking_session() -> Generator[Session]:
    __import__("app.models.uploaded_file")
    __import__("app.models.document_parsing")
    __import__("app.models.document_chunking")

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        yield session


# 种下分块所需的最小业务链路：用户、上传文件、解析作业、解析结果和一个 segment。
# 调用方用它测试 chunk 与已解析文档、用户和原始 segment 的关联。
def make_parsed_document_with_segment(
    session: Session,
    storage_root,
    user: User | None = None,
) -> tuple[User, UploadedFile, DocumentParseJob, ParsedDocument]:
    owner = user or make_user(session)
    upload = make_uploaded_file(session, storage_root, owner)
    job = DocumentParseJob(
        uploaded_file_id=upload.id,
        owner_user_id=owner.id,
        status="succeeded",
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    parsed = ParsedDocument(
        uploaded_file_id=upload.id,
        parse_job_id=job.id,
        owner_user_id=owner.id,
        source_checksum_sha256=upload.checksum_sha256,
        markdown_storage_key=f"parsed/{owner.id}/{upload.id}/{job.id}/content.md",
        text_storage_key=f"parsed/{owner.id}/{upload.id}/{job.id}/content.txt",
        docling_json_storage_key=f"parsed/{owner.id}/{upload.id}/{job.id}/docling.json",
        title="Course Notes",
        page_count=1,
        metadata_json={"source": "fixture"},
    )
    session.add(parsed)
    session.commit()
    session.refresh(parsed)

    session.add(
        DocumentSegment(
            parsed_document_id=parsed.id,
            owner_user_id=owner.id,
            sequence_index=0,
            segment_type="paragraph",
            page_no=1,
            heading_path=["Course Notes", "Retrieval"],
            text="Semantic retrieval should preserve source structure and stable ordering.",
            metadata_json={"docling_ref": "#/texts/0"},
        )
    )
    session.commit()
    return owner, upload, job, parsed


# 提供固定 UTC 时间。
# 需要断言 created_at/updated_at 等时间字段的测试用它避免时钟漂移。
def utc_fixture_time():
    return datetime(2026, 6, 12, tzinfo=UTC)


# 生成带业务前缀的随机 storage key。
# 用于测试只关心路径形态而不关心具体 UUID 的场景。
def random_storage_key(prefix: str = "chunks") -> str:
    return f"{prefix}/{uuid4()}"
