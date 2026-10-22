# 本文件提供用户体系测试的可复用辅助函数。
# 覆盖：带凭据账号的创建、真实会话 Cookie 的建立、既有资料接口测试的认证依赖覆盖，
# 以及“用户 → 上传 → 解析 → 分块 → 向量”最小知识链路的种子数据。

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db.session import get_session
from app.main import app
from app.models.user import User

DEFAULT_TEST_PASSWORD = "Knowra-Pass-2026"
SESSION_COOKIE = "knowra_session"
TRUSTED_ORIGIN = "http://localhost:5173"


def make_sqlite_session() -> Generator[Session]:
    # 创建导入了全部业务模型的内存 SQLite，供认证和隔离测试共享。
    __import__("app.models.uploaded_file")
    __import__("app.models.document_parsing")
    __import__("app.models.document_chunking")
    __import__("app.models.document_embedding")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def make_account(
    session: Session,
    *,
    email: str | None = None,
    password: str = DEFAULT_TEST_PASSWORD,
    role: str = "member",
    status: str = "active",
    display_name: str | None = None,
    deleted: bool = False,
    created_at: datetime | None = None,
) -> User:
    # 创建一个带 argon2 凭据的账号，邮箱默认唯一且已规范化。
    from app.models.user import UserCredential
    from app.services.passwords import hash_password

    email = email or f"user-{uuid4().hex[:8]}@example.com"
    timestamp = created_at or datetime.now(UTC)
    user = User(
        display_name=display_name or email.split("@")[0],
        email=email,
        role=role,
        status=status,
        deleted_at=timestamp if deleted else None,
        created_at=timestamp,
        updated_at=timestamp,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    session.add(UserCredential(user_id=user.id, password_hash=hash_password(password)))
    session.commit()
    return user


def issue_session_token(session: Session, user: User, *, ttl_hours: int = 1) -> str:
    # 通过会话服务为用户签发真实会话，返回 Cookie 中使用的原始令牌。
    from app.services.auth import create_session

    return create_session(session, user, ttl=timedelta(hours=ttl_hours))


def login_as(client: TestClient, session: Session, user: User) -> str:
    # 为 TestClient 设置真实的会话 Cookie，模拟浏览器登录态。
    token = issue_session_token(session, user)
    client.cookies.set(SESSION_COOKIE, token)
    return token


def authenticate_as(user: User) -> None:
    # 既有资料接口测试专注业务逻辑：直接覆盖认证依赖为指定用户，
    # 认证本身由 test_auth_api / test_authorization 用真实 Cookie 覆盖。
    from app.api.deps import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user


def override_db(session: Session) -> None:
    # 让应用使用测试 SQLite 会话。
    def _get_session() -> Generator[Session]:
        yield session

    app.dependency_overrides[get_session] = _get_session


def seed_knowledge_chain(session: Session, storage_root: Path, user: User, *, vectors: int = 2):
    # 为指定用户种下完整的已向量化资料链路，返回 (upload, parsed, chunk_job, chunks, embeddings)。
    from app.models.document_chunking import DocumentChunk, DocumentChunkJob
    from app.models.document_embedding import DocumentEmbedding, DocumentEmbeddingJob
    from tests.document_chunking_helpers import make_parsed_document_with_segment

    _owner, upload, _job, parsed = make_parsed_document_with_segment(
        session, storage_root, user=user, source_content=f"private fixture {uuid4()}".encode()
    )
    chunk_job = DocumentChunkJob(
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="succeeded",
        chunker_name="docling_hybrid",
        chunker_version="docling-core",
        chunk_config_json={"max_tokens": 512},
        chunk_count=vectors,
    )
    session.add(chunk_job)
    session.commit()
    session.refresh(chunk_job)

    chunks = []
    for index in range(vectors):
        chunk = DocumentChunk(
            chunk_job_id=chunk_job.id,
            parsed_document_id=parsed.id,
            owner_user_id=user.id,
            sequence_index=index,
            text=f"{user.display_name} 的私有片段 {index}",
            contextualized_text=f"Course Notes\n{user.display_name} 的私有片段 {index}",
            token_count=10,
            heading_path=["Course Notes"],
            page_numbers=[1],
            chunk_type="text",
            source_segment_indices=[0],
            metadata_json={},
        )
        session.add(chunk)
        chunks.append(chunk)
    session.commit()

    embedding_job = DocumentEmbeddingJob(
        chunk_job_id=chunk_job.id,
        parsed_document_id=parsed.id,
        owner_user_id=user.id,
        status="succeeded",
        embedder_name="openai_compatible",
        model="Qwen/Qwen3-Embedding-4B",
        dimensions=2560,
        embedding_count=vectors,
        config_json={"model": "Qwen/Qwen3-Embedding-4B", "dimensions": 2560},
    )
    session.add(embedding_job)
    session.commit()
    session.refresh(embedding_job)

    embeddings = []
    vector = [0.1] * 2560
    for chunk in chunks:
        session.refresh(chunk)
        embedding = DocumentEmbedding(
            embedding_job_id=embedding_job.id,
            chunk_id=chunk.id,
            parsed_document_id=parsed.id,
            owner_user_id=user.id,
            sequence_index=chunk.sequence_index,
            model="Qwen/Qwen3-Embedding-4B",
            dimensions=2560,
            embedding_json=vector,
            embedding_vector=vector,
            token_count=None,
        )
        session.add(embedding)
        embeddings.append(embedding)
    session.commit()
    return upload, parsed, chunk_job, chunks, embeddings


def expire_all_sessions_of(session: Session, user: User) -> None:
    # 把指定用户的全部会话改为已过期，用于验证绝对过期。
    from sqlmodel import select

    from app.models.user import UserSession

    past = datetime.now(UTC) - timedelta(minutes=1)
    for row in session.exec(select(UserSession).where(UserSession.user_id == user.id)).all():
        row.expires_at = past
        session.add(row)
    session.commit()
