# 用户体系红测试：管理命令 `python -m app.cli`。
# 覆盖创建管理员、显式认领旧默认用户、密码输入方式（stdin/getpass，不接受命令行参数）、
# 退出码语义，以及重置密码撤销会话。

import io
from datetime import timedelta

import pytest
from sqlmodel import Session, func, select

from app import cli
from app.models.uploaded_file import UploadedFile
from app.models.user import User, UserCredential
from app.services.auth import create_session, resolve_session_user
from app.services.passwords import verify_password
from app.services.users import DEFAULT_USER_ID
from tests.auth_helpers import DEFAULT_TEST_PASSWORD, make_account
from tests.document_parsing_helpers import SessionFactory, make_uploaded_file

ADMIN_PASSWORD = "Admin-Pass-2026"


def run(argv: list[str], session: Session, monkeypatch, *, stdin: str | None = None) -> int:
    if stdin is not None:
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return cli.main(argv, session_factory=SessionFactory(session))


def credential_of(session: Session, user: User) -> UserCredential | None:
    return session.exec(select(UserCredential).where(UserCredential.user_id == user.id)).first()


# 验证 create-admin 通过 stdin 读取密码，创建邮箱规范化的新管理员，输出不包含密码。
def test_create_admin_creates_new_admin(auth_db: Session, monkeypatch, capsys) -> None:
    code = run(
        [
            "create-admin",
            "--email",
            " Admin@Example.com ",
            "--display-name",
            "管理员",
            "--password-stdin",
        ],
        auth_db,
        monkeypatch,
        stdin=ADMIN_PASSWORD + "\n",
    )

    assert code == 0
    admin = auth_db.exec(select(User).where(User.email == "admin@example.com")).one()
    assert admin.role == "admin"
    assert admin.status == "active"
    assert admin.id != DEFAULT_USER_ID
    assert verify_password(credential_of(auth_db, admin).password_hash, ADMIN_PASSWORD)
    output = capsys.readouterr()
    assert ADMIN_PASSWORD not in output.out + output.err


# 验证交互模式通过 getpass 输入两次密码，一致时创建成功。
def test_create_admin_reads_password_with_getpass_twice(auth_db: Session, monkeypatch) -> None:
    prompts: list[str] = []

    def fake_getpass(prompt: str = "") -> str:
        prompts.append(prompt)
        return ADMIN_PASSWORD

    monkeypatch.setattr(cli, "getpass", fake_getpass)

    code = run(
        ["create-admin", "--email", "admin@example.com", "--display-name", "管理员"],
        auth_db,
        monkeypatch,
    )

    assert code == 0
    assert len(prompts) == 2


# 验证两次输入的密码不一致时退出码为 1，且不创建账号。
def test_create_admin_rejects_mismatched_passwords(auth_db: Session, monkeypatch) -> None:
    answers = iter([ADMIN_PASSWORD, "Different-Pass-2026"])
    monkeypatch.setattr(cli, "getpass", lambda prompt="": next(answers))

    code = run(
        ["create-admin", "--email", "admin@example.com", "--display-name", "管理员"],
        auth_db,
        monkeypatch,
    )

    assert code == 1
    assert auth_db.exec(select(User)).all() == []


# 验证弱密码退出码为 1，不创建账号。
def test_create_admin_rejects_weak_password(auth_db: Session, monkeypatch, capsys) -> None:
    code = run(
        [
            "create-admin",
            "--email",
            "admin@example.com",
            "--display-name",
            "管理员",
            "--password-stdin",
        ],
        auth_db,
        monkeypatch,
        stdin="short\n",
    )

    assert code == 1
    assert auth_db.exec(select(User)).all() == []
    assert "密码" in capsys.readouterr().err


# 验证命令不接受通过命令行参数传入密码，避免密码进入 shell 历史和进程列表。
def test_create_admin_does_not_accept_password_argument(auth_db: Session, monkeypatch) -> None:
    with pytest.raises(SystemExit):
        run(
            [
                "create-admin",
                "--email",
                "admin@example.com",
                "--display-name",
                "管理员",
                "--password",
                ADMIN_PASSWORD,
            ],
            auth_db,
            monkeypatch,
        )
    assert auth_db.exec(select(User)).all() == []


# 验证邮箱已存在时退出码为 2（前置条件不满足），已有账号角色不被修改。
def test_create_admin_rejects_existing_email(auth_db: Session, monkeypatch) -> None:
    existing = make_account(auth_db, email="admin@example.com", role="member")

    code = run(
        [
            "create-admin",
            "--email",
            "ADMIN@example.com",
            "--display-name",
            "管理员",
            "--password-stdin",
        ],
        auth_db,
        monkeypatch,
        stdin=ADMIN_PASSWORD + "\n",
    )

    assert code == 2
    auth_db.refresh(existing)
    assert existing.role == "member"
    assert len(auth_db.exec(select(User)).all()) == 1


# 验证 --claim-legacy-user 把无凭据的旧默认用户认领为管理员，旧资料归属保持不变。
def test_create_admin_claims_legacy_default_user(auth_db: Session, monkeypatch, tmp_path) -> None:
    legacy = User(id=DEFAULT_USER_ID, display_name="Default User", status="active")
    auth_db.add(legacy)
    auth_db.commit()
    make_uploaded_file(auth_db, tmp_path / "uploads", legacy)

    code = run(
        [
            "create-admin",
            "--email",
            "owner@example.com",
            "--display-name",
            "资料主人",
            "--claim-legacy-user",
            "--password-stdin",
        ],
        auth_db,
        monkeypatch,
        stdin=ADMIN_PASSWORD + "\n",
    )

    assert code == 0
    auth_db.refresh(legacy)
    assert (legacy.email, legacy.display_name, legacy.role) == (
        "owner@example.com",
        "资料主人",
        "admin",
    )
    assert verify_password(credential_of(auth_db, legacy).password_hash, ADMIN_PASSWORD)
    assert len(auth_db.exec(select(User)).all()) == 1
    owned = auth_db.exec(
        select(func.count())
        .select_from(UploadedFile)
        .where(UploadedFile.owner_user_id == DEFAULT_USER_ID)
    ).one()
    assert owned == 1


# 验证旧默认用户不存在或已有凭据（已被认领）时，认领失败且退出码为 2。
@pytest.mark.parametrize("state", ["missing", "already_claimed"])
def test_claim_legacy_user_requires_unclaimed_legacy_row(
    auth_db: Session, monkeypatch, state: str
) -> None:
    if state == "already_claimed":
        legacy = User(id=DEFAULT_USER_ID, display_name="Default User", email="old@example.com")
        auth_db.add(legacy)
        auth_db.commit()
        from app.services.passwords import hash_password

        auth_db.add(
            UserCredential(user_id=DEFAULT_USER_ID, password_hash=hash_password("Old-Pass-2026"))
        )
        auth_db.commit()

    code = run(
        [
            "create-admin",
            "--email",
            "owner@example.com",
            "--display-name",
            "资料主人",
            "--claim-legacy-user",
            "--password-stdin",
        ],
        auth_db,
        monkeypatch,
        stdin=ADMIN_PASSWORD + "\n",
    )

    assert code == 2
    assert auth_db.exec(select(User).where(User.email == "owner@example.com")).first() is None


# 验证 reset-password 设置新密码并撤销该用户全部会话。
def test_reset_password_sets_new_password_and_revokes_sessions(
    auth_db: Session, monkeypatch
) -> None:
    user = make_account(auth_db, email="alice@example.com")
    token = create_session(auth_db, user, ttl=timedelta(hours=1))

    code = run(
        ["reset-password", "--email", "ALICE@example.com", "--password-stdin"],
        auth_db,
        monkeypatch,
        stdin="Reset-Pass-2026\n",
    )

    assert code == 0
    assert resolve_session_user(auth_db, token) is None
    credential = credential_of(auth_db, user)
    auth_db.refresh(credential)
    assert verify_password(credential.password_hash, "Reset-Pass-2026")
    assert not verify_password(credential.password_hash, DEFAULT_TEST_PASSWORD)


# 验证重置不存在的邮箱时退出码为 2。
def test_reset_password_unknown_email(auth_db: Session, monkeypatch) -> None:
    code = run(
        ["reset-password", "--email", "nobody@example.com", "--password-stdin"],
        auth_db,
        monkeypatch,
        stdin="Reset-Pass-2026\n",
    )

    assert code == 2
