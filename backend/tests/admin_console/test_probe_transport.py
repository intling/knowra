"""诊断连接目标校验应约束实际 TCP 连接。"""

import importlib

import pytest


# 验证私网与本机模型允许，元数据、链路本地、未指定地址及映射 IPv6 均拒绝。
@pytest.mark.parametrize(
    "address,allowed",
    [
        ("127.0.0.1", True),
        ("10.2.3.4", True),
        ("::1", True),
        ("192.168.1.2", True),
        ("169.254.169.254", False),
        ("100.100.100.200", False),
        ("fe80::1", False),
        ("::ffff:169.254.169.254", False),
        ("0.0.0.0", False),
    ],
)
def test_target_policy(address, allowed):
    service = importlib.import_module("app.services.model_probe_transport")
    assert service.allowed_address(address) is allowed, "诊断目标策略必须允许私有部署并阻止元数据"


# 验证 DNS 验证通过后实际连接使用选中的数字 IP，防止二次解析绕过校验。
@pytest.mark.asyncio
async def test_dns_resolution_is_pinned_to_actual_connection(monkeypatch):
    service = importlib.import_module("app.services.model_probe_transport")

    async def resolve(*args, **kwargs):
        return [(2, 1, 6, "", ("127.0.0.1", 8080))]

    calls = []

    async def connect(self, host, port, **kwargs):
        calls.append((host, port))
        return "stream"

    monkeypatch.setattr(service.anyio, "getaddrinfo", resolve)
    monkeypatch.setattr(service.AnyIOBackend, "connect_tcp", connect)
    assert await service.ProbeNetworkBackend().connect_tcp("model.internal", 8080) == "stream"
    assert calls == [("127.0.0.1", 8080)], "连接不得再次使用未约束域名"


# 验证混合 DNS 解析只要包含危险目标即拒绝，不能回落到未经校验地址。
@pytest.mark.asyncio
async def test_mixed_dns_metadata_answer_is_blocked(monkeypatch):
    service = importlib.import_module("app.services.model_probe_transport")

    async def resolve(*args, **kwargs):
        return [(2, 1, 6, "", ("127.0.0.1", 80)), (2, 1, 6, "", ("169.254.169.254", 80))]

    monkeypatch.setattr(service.anyio, "getaddrinfo", resolve)
    with pytest.raises(Exception, match="blocked"):
        await service.ProbeNetworkBackend().connect_tcp("model.internal", 80)


# 验证真实本机 HTTP 连接可用、重定向不被跟随；传输本身不读取任何生产模型配置。
@pytest.mark.asyncio
async def test_actual_loopback_transport_and_redirect():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    import httpx

    service = importlib.import_module("app.services.model_probe_transport")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        async with httpx.AsyncClient(
            transport=service.ProbeTransport(), follow_redirects=False
        ) as client:
            response = await client.get(f"http://127.0.0.1:{server.server_port}/", timeout=1)
            assert response.status_code == 302
            assert not response.history, "实际传输不能跟随元数据重定向"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(1)
