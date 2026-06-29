import logging

from fastapi.testclient import TestClient


def test_health_check_returns_service_status(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "app_name": "knowra",
        "environment": "local",
    }


# 测试健康检查路由应输出 DEBUG 级别日志，包含 app_name 和 environment。
def test_health_check_logs_debug(client: TestClient, caplog) -> None:
    caplog.set_level(logging.DEBUG)

    client.get("/api/health")

    route_records = [r for r in caplog.records if r.name == "app.api.routes.health"]
    assert any(r.levelname == "DEBUG" for r in route_records)
