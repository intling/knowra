import pytest


@pytest.fixture(autouse=True)
def _use_fast_password_hasher(fast_password_hasher):
    """用户体系测试目录下默认启用低成本密码哈希参数。"""
    yield
