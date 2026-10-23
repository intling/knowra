"""诊断专用传输：DNS 解析与实际连接绑定，保留原域名 TLS 校验。"""

import ipaddress
import socket

import anyio
import httpcore
import httpx
from httpcore._backends.anyio import AnyIOBackend


def allowed_address(value: str) -> bool:
    address = ipaddress.ip_address(value.split("%")[0])
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return not (
        address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or str(address) in {"100.100.100.200", "168.63.129.16", "fd00:ec2::254"}
    )


class ProbeNetworkBackend(httpcore.AsyncNetworkBackend):
    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        answers = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
        if not addresses or any(not allowed_address(address) for address in addresses):
            raise httpcore.ConnectError("blocked diagnostic target")
        # httpcore 仍以原始 hostname 完成 SNI/证书验证；底层 TCP 仅连接已验证数字 IP。
        return await AnyIOBackend().connect_tcp(
            addresses[0],
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def sleep(self, seconds):
        await anyio.sleep(seconds)


class ProbeTransport(httpx.AsyncHTTPTransport):
    def __init__(self):
        super().__init__(retries=0, trust_env=False)
        # HTTPX 尚未暴露 network_backend 注入。仅此适配层触及其连接池边界。
        self._pool = httpcore.AsyncConnectionPool(
            network_backend=ProbeNetworkBackend(), retries=0, max_connections=1
        )
