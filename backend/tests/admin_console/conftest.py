"""后台管理测试使用现有真实 Cookie 认证与内存数据库，不访问外部模型。"""

from base64 import urlsafe_b64encode

import pytest

from app.core.config import Settings, get_settings
from app.main import app
from tests.auth_helpers import login_as, make_account


@pytest.fixture
def admin_actor(auth_client, auth_db):
    # 为每个管理测试签发独立管理员会话，避免污染既有账号与凭据。
    actor = make_account(auth_db, email="console-admin@example.com", role="admin")
    login_as(auth_client, auth_db, actor)
    return actor


@pytest.fixture
def model_settings(auth_client):
    # 注入仅用于测试的加密主密钥和独立环境回退，不读取真实 .env 密钥。
    settings = Settings(
        _env_file=None,
        model_config_encryption_key=urlsafe_b64encode(b"k" * 32).decode(),
        chat_api_base_url="https://environment.example/v1",
        chat_api_key="environment-chat-test-key",
        chat_model="environment-chat",
        document_embedding_api_base_url="https://embedding.example/v1",
        document_embedding_api_key="environment-embedding-test-key",
        query_rewrite_enabled=False,
        rerank_enabled=False,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    return settings
