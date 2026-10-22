"""普通演示成员初始化命令的 RED 测试，不使用真实账号密码。"""

import importlib
import io

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app import cli
from app.models.user import User, UserCredential
from app.services.passwords import verify_password
from tests.auth_helpers import make_account
from tests.document_parsing_helpers import SessionFactory

FIXTURE_PASSWORD = "D3mo-Test^$Pass@2026"


def create_member(session, monkeypatch, *, email="visitor@example.com", extra=None, password=None):
    # 特殊符号密码从 stdin 输入，命令行参数和测试输出不携带秘密。
    monkeypatch.setattr("sys.stdin", io.StringIO((password or FIXTURE_PASSWORD) + "\n"))
    return cli.main(
        [
            "create-user",
            "--email",
            email,
            "--display-name",
            "演示访客",
            "--password-stdin",
            *(extra or []),
        ],
        session_factory=SessionFactory(session),
    )


# 验证创建 active member、规范化邮箱、哈希凭据及小时 3 次额度，输出不包含密码。
def test_create_member_with_hourly_limit(auth_db, fast_password_hasher, monkeypatch, capsys):
    result = create_member(
        auth_db, monkeypatch, email=" Visitor@Example.com ", extra=["--hourly-chat-limit", "3"]
    )
    assert result == 0
    limit_model = importlib.import_module("app.models.chat_quota").UserChatLimit
    user = auth_db.exec(select(User).where(User.email == "visitor@example.com")).one()
    assert (user.status, user.role, user.display_name) == ("active", "member", "演示访客")
    credential = auth_db.get(UserCredential, user.id)
    assert verify_password(credential.password_hash, FIXTURE_PASSWORD)
    assert credential.password_hash != FIXTURE_PASSWORD
    assert auth_db.get(limit_model, user.id).hourly_limit == 3
    output = capsys.readouterr()
    assert FIXTURE_PASSWORD not in output.out + output.err


# 验证不指定限额时创建普通无限制成员，不创建隐含演示限制。
def test_create_member_without_limit(auth_db, fast_password_hasher, monkeypatch):
    assert create_member(auth_db, monkeypatch) == 0
    limit_model = importlib.import_module("app.models.chat_quota").UserChatLimit
    user = auth_db.exec(select(User).where(User.email == "visitor@example.com")).one()
    assert user.role == "member"
    assert auth_db.get(limit_model, user.id) is None


# 验证重复邮箱拒绝，已有账号角色、密码及总用户数不能被创建命令改变。
def test_duplicate_email_does_not_change_existing_user(auth_db, fast_password_hasher, monkeypatch):
    user = make_account(auth_db, email="visitor@example.com", role="admin")
    old_hash = auth_db.get(UserCredential, user.id).password_hash

    assert create_member(auth_db, monkeypatch, extra=["--hourly-chat-limit", "3"]) == 2

    auth_db.refresh(user)
    assert user.role == "admin"
    assert auth_db.get(UserCredential, user.id).password_hash == old_hash
    assert len(auth_db.exec(select(User)).all()) == 1


# 验证无效小时额度给出明确错误，不能写入用户或凭据半成品。
@pytest.mark.parametrize("limit", ["0", "-1", "1.5", "abc"])
def test_invalid_limit_creates_nothing(auth_db, monkeypatch, capsys, limit):
    try:
        result = create_member(auth_db, monkeypatch, extra=["--hourly-chat-limit", limit])
    except SystemExit as error:
        result = error.code

    assert result != 0
    assert auth_db.exec(select(User)).all() == []
    output = capsys.readouterr()
    assert "hourly-chat-limit" in output.err or "额度" in output.err


# 验证弱密码拒绝并提供可读原因，不能留下账号和额度。
def test_weak_password_creates_nothing(auth_db, monkeypatch, capsys):
    assert create_member(auth_db, monkeypatch, password="short") == 1
    assert auth_db.exec(select(User)).all() == []
    assert "密码" in capsys.readouterr().err


# 验证交互模式使用两次 getpass，不匹配时拒绝创建成员。
def test_member_interactive_password_confirmation(auth_db, monkeypatch, capsys):
    answers = iter([FIXTURE_PASSWORD, "Different-Pass-2026"])
    monkeypatch.setattr(cli, "getpass", lambda prompt="": next(answers))

    result = cli.main(
        ["create-user", "--email", "visitor@example.com", "--display-name", "演示访客"],
        session_factory=SessionFactory(auth_db),
    )

    assert result == 1
    assert auth_db.exec(select(User)).all() == []
    assert "不一致" in capsys.readouterr().err


# 验证额度记录写入失败时账号与凭据同事务回滚，不能留下无限制成员。
def test_quota_insert_failure_is_atomic(auth_db, fast_password_hasher, monkeypatch):
    limit_model = importlib.import_module("app.models.chat_quota").UserChatLimit
    original_add = auth_db.add

    def fail_on_quota(instance, **kwargs):
        # 注入确定性数据库错误，验证命令未提前提交用户与凭据。
        if isinstance(instance, limit_model):
            raise IntegrityError("quota fixture failure", {}, Exception("fixture"))
        return original_add(instance, **kwargs)

    monkeypatch.setattr(auth_db, "add", fail_on_quota)
    assert create_member(auth_db, monkeypatch, extra=["--hourly-chat-limit", "3"]) != 0
    auth_db.rollback()
    assert auth_db.exec(select(User)).all() == []
    assert auth_db.exec(select(UserCredential)).all() == []
