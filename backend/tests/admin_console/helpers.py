"""后台 API 契约断言与模型配置夹具。"""

MODEL_KEY = "console-model-secret-only-for-tests"


def assert_status(response, expected: int, condition: str):
    # 状态断言携带业务条件和实际响应，避免只能看到笼统的 404/405。
    assert response.status_code == expected, (
        f"{condition}：期望 HTTP {expected}，实际 HTTP {response.status_code}；响应={response.text}"
    )
    return response.json() if expected not in (204,) else None


def assert_error(response, status: int, code: str, condition: str):
    body = assert_status(response, status, condition)
    assert body.get("code") == code, f"{condition}：期望错误码 {code}，实际 {body}"
    assert isinstance(body.get("detail"), str) and body["detail"].strip(), (
        f"{condition}：必须返回可读错误原因，实际 {body}"
    )
    return body


def profile_payload(kind="chat", **changes):
    payload = {
        "name": f"测试 {kind} 配置",
        "kind": kind,
        "base_url": "https://models.example/v1",
        "model": f"test-{kind}",
        "api_key": MODEL_KEY,
        "timeout_seconds": 12,
        "max_retries": 1,
    }
    if kind == "embedding":
        payload["dimensions"] = 2560
    if kind == "rerank":
        payload.update(api_format="compatible", max_retries=0)
    return payload | changes


def create_profile(client, kind="chat", **changes):
    return assert_status(
        client.post("/api/admin/models", json=profile_payload(kind, **changes)),
        201,
        f"管理员创建 {kind} 模型配置必须返回公开配置，不能缺少创建接口",
    )


def activate_profile(client, profile):
    return assert_status(
        client.post(f"/api/admin/models/{profile['id']}/activate"),
        200,
        f"激活 {profile['kind']} 配置必须成功并切换该用途默认模型",
    )
