"""开启数据库外键，复现 PostgreSQL 新账号父子记录插入顺序。"""

import io

import pytest
from sqlmodel import select

from app import cli
from app.models.chat_quota import UserChatLimit
from app.models.user import User, UserCredential
from app.services.auth import register_user
from tests.document_parsing_helpers import SessionFactory


# 验证启用外键后，CLI 先写用户再写凭据/额度，仍在同一事务内创建。
@pytest.mark.parametrize("command", ["create-user", "create-admin"])
def test_cli_creates_account_with_foreign_keys(auth_db, fast_password_hasher, monkeypatch, command):
    auth_db.connection().exec_driver_sql("PRAGMA foreign_keys=ON")
    monkeypatch.setattr("sys.stdin", io.StringIO("Synthetic-Pass-2026\n"))
    extra = ["--hourly-chat-limit", "3"] if command == "create-user" else []
    result = cli.main(
        [
            command,
            "--email",
            "foreign-key@example.com",
            "--display-name",
            "外键验证",
            "--password-stdin",
            *extra,
        ],
        session_factory=SessionFactory(auth_db),
    )
    assert result == 0, "新账号的父用户记录必须在凭据和额度外键写入前存在"
    user = auth_db.exec(select(User).where(User.email == "foreign-key@example.com")).one()
    assert auth_db.get(UserCredential, user.id) is not None
    if command == "create-user":
        assert auth_db.get(UserChatLimit, user.id).hourly_limit == 3


# 验证公开注册同样遵守真实数据库外键，不能把新邮箱错误报告为已被占用。
def test_registration_creates_account_with_foreign_keys(auth_db, fast_password_hasher):
    auth_db.connection().exec_driver_sql("PRAGMA foreign_keys=ON")
    user = register_user(
        auth_db,
        email="new-member@example.com",
        display_name="注册验证",
        password="Synthetic-Pass-2026",
    )
    assert auth_db.get(UserCredential, user.id) is not None
