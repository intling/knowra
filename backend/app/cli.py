"""Explicit administrator bootstrap and password recovery commands."""

import argparse
import sys
from getpass import getpass

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.session import engine
from app.models.chat_quota import UserChatLimit
from app.models.user import User, UserCredential, utc_now
from app.services.auth import revoke_user_sessions
from app.services.passwords import (
    hash_password,
    normalize_display_name,
    normalize_email,
    validate_password,
)
from app.services.users import DEFAULT_USER_ID

logger = get_logger(__name__)


def default_session_factory():
    return Session(engine)


def main(argv: list[str] | None = None, *, session_factory=default_session_factory) -> int:
    parser = argparse.ArgumentParser(description="knowra 账号管理", allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-admin", allow_abbrev=False)
    create.add_argument("--email", required=True)
    create.add_argument("--display-name", required=True)
    create.add_argument("--claim-legacy-user", action="store_true")
    create.add_argument("--password-stdin", action="store_true")
    member = commands.add_parser("create-user", allow_abbrev=False)
    member.add_argument("--email", required=True)
    member.add_argument("--display-name", required=True)
    member.add_argument("--hourly-chat-limit", type=int)
    member.add_argument("--password-stdin", action="store_true")
    reset = commands.add_parser("reset-password", allow_abbrev=False)
    reset.add_argument("--email", required=True)
    reset.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args(argv)
    try:
        hourly_limit = getattr(args, "hourly_chat_limit", None)
        if hourly_limit is not None and hourly_limit <= 0:
            raise AppError(422, "invalid_chat_limit", "小时问答额度必须是正整数")
        email = normalize_email(args.email)
        password = sys.stdin.readline().rstrip("\r\n") if args.password_stdin else getpass("密码：")
        if not args.password_stdin and password != getpass("再次输入密码："):
            raise AppError(422, "password_mismatch", "两次输入的密码不一致")
        validate_password(password, email=email)
        with session_factory() as session:
            existing = session.exec(select(User).where(User.email == email)).first()
            if args.command in {"create-admin", "create-user"}:
                display_name = normalize_display_name(args.display_name)
                if existing is not None:
                    raise AppError(409, "email_taken", "此邮箱已注册")
                claim_legacy = getattr(args, "claim_legacy_user", False)
                if claim_legacy:
                    user = session.get(User, DEFAULT_USER_ID)
                    if (
                        user is None
                        or user.deleted_at is not None
                        or session.get(UserCredential, user.id)
                    ):
                        raise AppError(
                            409, "legacy_unavailable", "默认账号不存在、已删除或已被认领"
                        )
                    user.email, user.display_name = email, display_name
                    user.role, user.status = "admin", "active"
                    user.updated_at = utc_now()
                else:
                    user = User(
                        email=email,
                        display_name=display_name,
                        role="admin" if args.command == "create-admin" else "member",
                    )
                session.add(user)
                session.add(UserCredential(user_id=user.id, password_hash=hash_password(password)))
                if hourly_limit is not None:
                    # 额度映射可能先于用户写入；先刷新父记录，保持单次提交的原子性。
                    session.flush()
                    session.add(UserChatLimit(user_id=user.id, hourly_limit=hourly_limit))
                session.commit()
                logger.info(
                    "账号已创建", user_id=str(user.id), role=user.role, claimed_legacy=claim_legacy
                )
            else:
                if existing is None or existing.deleted_at is not None:
                    raise AppError(404, "user_not_found", "邮箱对应的账号不存在")
                credential = session.get(UserCredential, existing.id)
                if credential is None:
                    credential = UserCredential(
                        user_id=existing.id, password_hash=hash_password(password)
                    )
                else:
                    credential.password_hash = hash_password(password)
                    credential.updated_at = utc_now()
                session.add(credential)
                revoke_user_sessions(session, existing.id, commit=False)
                session.commit()
                logger.info("密码已重置", user_id=str(existing.id), reason="all_sessions_revoked")
    except AppError as exc:
        sys.stderr.write(exc.detail + "\n")
        return 1 if exc.status_code == 422 else 2
    except IntegrityError:
        sys.stderr.write("邮箱或账号已被占用\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
