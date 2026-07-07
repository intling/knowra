import logging
from types import SimpleNamespace

from fastapi.testclient import TestClient


def make_document_model_readiness(
    *,
    status: str,
    docling_status: str | None = None,
    tokenizer_status: str | None = None,
    docling_missing_models: list[str] | None = None,
    tokenizer_missing_models: list[str] | None = None,
):
    return SimpleNamespace(
        status=status,
        docling=SimpleNamespace(
            status=docling_status or status,
            missing_models=docling_missing_models or [],
        ),
        tokenizer=SimpleNamespace(
            status=tokenizer_status or status,
            missing_models=tokenizer_missing_models or [],
        ),
    )


# 测试健康检查保留既有服务状态字段，并返回文档模型 ready 摘要。
# 该测试驱动复用 /api/health 暴露模型 readiness，而不是新增独立 endpoint。
def test_health_check_returns_service_status(client: TestClient) -> None:
    client.app.state.document_model_readiness = make_document_model_readiness(
        status="ready",
        docling_status="ready",
        tokenizer_status="ready",
    )

    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["app_name"] == "knowra"
    assert payload["environment"] == "local"
    assert payload["document_models"] == {
        "status": "ready",
        "docling": {"status": "ready", "missing_models": []},
        "tokenizer": {"status": "ready", "missing_models": []},
    }


# 测试 degraded 启动后健康检查仍返回 200，并暴露模型缺失诊断。
# 该测试让部署侧能通过现有 health 响应看到文档模型不可用状态。
def test_health_check_returns_document_model_degraded_summary(client: TestClient) -> None:
    client.app.state.document_model_readiness = make_document_model_readiness(
        status="unavailable",
        docling_status="unavailable",
        tokenizer_status="ready",
        docling_missing_models=["layout"],
    )

    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_models"]["status"] == "unavailable"
    assert payload["document_models"]["docling"] == {
        "status": "unavailable",
        "missing_models": ["layout"],
    }
    assert payload["document_models"]["tokenizer"] == {
        "status": "ready",
        "missing_models": [],
    }


# 测试禁用模型 bootstrap 时，健康检查表达 skipped 状态。
# 该测试覆盖配置关闭后的可观测性，不要求模型目录存在。
def test_health_check_returns_document_model_skipped_summary(client: TestClient) -> None:
    client.app.state.document_model_readiness = make_document_model_readiness(status="skipped")

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["document_models"]["status"] == "skipped"


# 测试健康检查在模型内存预加载期间返回 loading 摘要。
# 该测试驱动现有 /api/health 暴露非阻塞预加载状态。
def test_health_check_returns_document_model_loading_summary(client: TestClient) -> None:
    client.app.state.document_model_readiness = make_document_model_readiness(
        status="loading",
        docling_status="loading",
        tokenizer_status="loading",
    )

    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_models"] == {
        "status": "loading",
        "docling": {"status": "loading", "missing_models": []},
        "tokenizer": {"status": "loading", "missing_models": []},
    }


# 测试应用进入 graceful shutdown 后，现有 health 摘要表达模型不可服务状态。
# 该测试驱动关闭期复用 /api/health 暴露 shutting_down，而不是新增 endpoint。
def test_health_check_returns_document_model_shutting_down_summary(
    client: TestClient,
) -> None:
    client.app.state.document_model_readiness = make_document_model_readiness(
        status="ready",
        docling_status="ready",
        tokenizer_status="ready",
    )
    client.app.state.application_shutdown_state = SimpleNamespace(
        is_shutting_down=True,
        reason="signal",
    )
    try:
        response = client.get("/api/health")
    finally:
        delattr(client.app.state, "application_shutdown_state")

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_models"] == {
        "status": "shutting_down",
        "docling": {"status": "shutting_down", "missing_models": []},
        "tokenizer": {"status": "shutting_down", "missing_models": []},
    }


# 测试首版不新增独立文档模型健康检查 endpoint。
# 模型 readiness 必须通过既有 /api/health 的摘要暴露。
def test_health_check_does_not_add_dedicated_document_models_endpoint(
    client: TestClient,
) -> None:
    response = client.get("/api/health/document-models")

    assert response.status_code == 404


# 测试健康检查路由应输出 DEBUG 级别日志，包含 app_name 和 environment。
def test_health_check_logs_debug(client: TestClient, caplog) -> None:
    caplog.set_level(logging.DEBUG)

    client.get("/api/health")

    route_records = [r for r in caplog.records if r.name == "app.api.routes.health"]
    assert any(r.levelname == "DEBUG" for r in route_records)
