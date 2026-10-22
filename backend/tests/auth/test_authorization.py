# 用户体系红测试：全链路授权。
# 覆盖：私有路由清单统一要求登录、只读用户写接口 403 且无副作用、
# 跨用户资源标识返回与不存在一致的 404 且不泄露内容。

import re
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlmodel import Session, func, select

from app.core.config import get_settings
from app.main import app
from app.models.document_chunking import DocumentChunkJob
from app.models.document_embedding import DocumentEmbeddingJob
from app.models.document_parsing import DocumentParseJob
from app.models.uploaded_file import UploadedFile
from tests.auth_helpers import login_as, make_account, seed_knowledge_chain

PUBLIC_ROUTES = {
    ("GET", "/api/health"),
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
}


def private_api_routes() -> list[tuple[str, str]]:
    prefix = get_settings().api_prefix
    routes: list[tuple[str, str]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith(prefix):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            if (method, route.path) not in PUBLIC_ROUTES:
                routes.append((method, route.path))
    return routes


@pytest.fixture
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_STORAGE_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    yield tmp_path / "uploads"
    get_settings.cache_clear()


# 验证路由清单完整：业务接口全部挂载，且公开接口只有健康检查与 /auth 三个入口。
def test_route_inventory_contains_auth_and_admin_endpoints() -> None:
    all_routes = {(m, p) for m, p in private_api_routes()} | PUBLIC_ROUTES
    for expected in [
        ("GET", "/api/users/me"),
        ("PATCH", "/api/users/me"),
        ("POST", "/api/users/me/password"),
        ("GET", "/api/admin/users"),
        ("PATCH", "/api/admin/users/{user_id}"),
        ("POST", "/api/search"),
        ("POST", "/api/uploads"),
    ]:
        assert expected in all_routes, f"缺少接口 {expected}"


# 验证除公开白名单外，所有 /api 路由在未登录时都返回 401 auth_required，防止新接口漏挂认证。
def test_every_private_route_requires_authentication(auth_client: TestClient) -> None:
    unprotected: list[str] = []
    for method, path in private_api_routes():
        url = re.sub(r"\{[^}]+\}", str(uuid4()), path)
        response = auth_client.request(method, url, json={} if method != "GET" else None)
        if response.status_code != 401 or response.json().get("code") != "auth_required":
            unprotected.append(f"{method} {path} -> {response.status_code} {response.text[:120]}")

    assert unprotected == [], "以下私有接口未强制登录：\n" + "\n".join(unprotected)


# 验证 viewer 调用全部资料写接口均返回 403 forbidden，且不写入记录、不创建任务、不落盘。
def test_viewer_cannot_call_write_endpoints(
    auth_client: TestClient, auth_db: Session, isolated_storage, tmp_path
) -> None:
    viewer = make_account(auth_db, role="viewer")
    upload, parsed, chunk_job, _chunks, _embeddings = seed_knowledge_chain(
        auth_db, tmp_path / "seed-uploads", viewer
    )
    login_as(auth_client, auth_db, viewer)

    def counts() -> tuple[int, int, int, int]:
        return tuple(
            auth_db.exec(select(func.count()).select_from(model)).one()
            for model in (UploadedFile, DocumentParseJob, DocumentChunkJob, DocumentEmbeddingJob)
        )

    before = counts()
    responses = {
        "upload": auth_client.post(
            "/api/uploads", files={"file": ("notes.txt", b"notes", "text/plain")}
        ),
        "parse": auth_client.post(f"/api/uploads/{upload.id}/parse"),
        "rechunk": auth_client.post(f"/api/parsed-documents/{parsed.id}/rechunk", json={}),
        "re-embed": auth_client.post(f"/api/document-chunk-jobs/{chunk_job.id}/re-embed", json={}),
    }

    for name, response in responses.items():
        assert response.status_code == 403, f"{name} 应返回 403，实际 {response.status_code}"
        body = response.json()
        assert body["code"] == "forbidden", f"{name} 错误码应为 forbidden：{body}"
        assert "只读" in body["detail"] or "权限" in body["detail"], body
    assert counts() == before, "只读用户被拒绝的写请求不得产生任何记录或任务"
    assert not isolated_storage.exists() or not any(isolated_storage.rglob("*")), (
        "只读用户被拒绝的上传不得写入存储"
    )


# 验证 viewer 仍可读取和核对自己的资料。
def test_viewer_can_read_own_documents(auth_client: TestClient, auth_db: Session, tmp_path) -> None:
    viewer = make_account(auth_db, role="viewer")
    _upload, parsed, _chunk_job, chunks, _embeddings = seed_knowledge_chain(
        auth_db, tmp_path / "uploads", viewer
    )
    login_as(auth_client, auth_db, viewer)

    listing = auth_client.get("/api/parsed-documents")
    assert listing.status_code == 200, listing.text
    assert [item["id"] for item in listing.json()] == [str(parsed.id)]
    assert auth_client.get(f"/api/parsed-documents/{parsed.id}/segments").status_code == 200
    assert auth_client.get(f"/api/document-chunks/{chunks[0].id}").status_code == 200


# 验证用户 B 访问用户 A 的各类资源 UUID 时，读写接口均返回 404，且响应不含 A 的内容。
def test_cross_user_resource_access_returns_404(
    auth_client: TestClient, auth_db: Session, tmp_path
) -> None:
    owner = make_account(auth_db, display_name="Alice")
    intruder = make_account(auth_db, display_name="Bob")
    upload, parsed, chunk_job, chunks, _embeddings = seed_knowledge_chain(
        auth_db, tmp_path / "uploads", owner
    )
    embedding_job = auth_db.exec(select(DocumentEmbeddingJob)).one()
    parse_job = auth_db.exec(select(DocumentParseJob)).one()
    login_as(auth_client, auth_db, intruder)

    requests = [
        ("GET", f"/api/document-parse-jobs/{parse_job.id}"),
        ("GET", f"/api/uploads/{upload.id}/parsed-document"),
        ("GET", f"/api/parsed-documents/{parsed.id}/segments"),
        ("GET", f"/api/parsed-documents/{parsed.id}/chunks"),
        ("GET", f"/api/parsed-documents/{parsed.id}/chunk-job"),
        ("GET", f"/api/parsed-documents/{parsed.id}/pipeline-verification"),
        ("GET", f"/api/document-chunk-jobs/{chunk_job.id}"),
        ("GET", f"/api/document-chunk-jobs/{chunk_job.id}/embeddings"),
        ("GET", f"/api/document-chunk-jobs/{chunk_job.id}/embedding-job"),
        ("GET", f"/api/document-embedding-jobs/{embedding_job.id}"),
        ("GET", f"/api/document-chunks/{chunks[0].id}"),
        ("GET", f"/api/document-chunks/{chunks[0].id}/embedding"),
        ("POST", f"/api/uploads/{upload.id}/parse"),
        ("POST", f"/api/parsed-documents/{parsed.id}/rechunk"),
        ("POST", f"/api/document-chunk-jobs/{chunk_job.id}/re-embed"),
    ]
    leaked: list[str] = []
    for method, url in requests:
        response = auth_client.request(method, url, json={} if method == "POST" else None)
        if response.status_code != 404:
            leaked.append(f"{method} {url} -> {response.status_code}")
        elif "Alice" in response.text or "notes.pdf" in response.text:
            leaked.append(f"{method} {url} 404 响应泄露了资源内容")

    assert leaked == [], "跨用户访问必须返回与不存在一致的 404：\n" + "\n".join(leaked)
    assert auth_client.get("/api/parsed-documents").json() == []
