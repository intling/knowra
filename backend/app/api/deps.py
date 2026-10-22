from collections.abc import Generator
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlmodel import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.permissions import KNOWLEDGE_READ, KNOWLEDGE_WRITE, permissions_for
from app.db.session import get_session
from app.models.user import User
from app.schemas.search import SearchRequest
from app.services.auth import SESSION_COOKIE, LoginRateLimiter, resolve_session_user
from app.services.chat_quota import release_chat, reserve_chat

logger = get_logger(__name__)
SessionDep = Annotated[Session, Depends(get_session)]


def get_model_settings(
    session: SessionDep, settings: Annotated[Settings, Depends(get_settings)]
) -> Settings:
    from app.services.model_configuration import resolve_model_settings

    return resolve_model_settings(session, settings)


def get_current_user(request: Request, session: SessionDep) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    user = resolve_session_user(session, token)
    if user is None:
        logger.info(
            "认证失败",
            path=request.url.path,
            reason="invalid_session" if token else "missing_session",
        )
        raise AppError(401, "auth_required", "登录已失效，请重新登录" if token else "请先登录")
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def require_permission(permission: str):
    def check_permission(user: CurrentUserDep) -> User:
        if permission not in permissions_for(user.role):
            logger.warning("权限不足", user_id=str(user.id), permission=permission)
            raise AppError(403, "forbidden", "缺少操作权限：" + permission)
        return user

    return check_permission


ReadUserDep = Annotated[User, Depends(require_permission(KNOWLEDGE_READ))]
WriteUserDep = Annotated[User, Depends(require_permission(KNOWLEDGE_WRITE))]


@dataclass
class ChatAdmission:
    reservation_id: UUID | None
    succeeded: bool = False


def admit_chat(
    request: SearchRequest, user: ReadUserDep, session: SessionDep
) -> Generator[ChatAdmission]:
    admission = ChatAdmission(reserve_chat(session, user.id))
    try:
        yield admission
    finally:
        if not admission.succeeded:
            try:
                release_chat(session, admission.reservation_id)
            except Exception:
                logger.warning("问答额度释放失败", reservation_id=str(admission.reservation_id))


ChatAdmissionDep = Annotated[ChatAdmission, Depends(admit_chat, scope="function")]


def verify_trusted_origin(request: Request) -> None:
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    origin = request.headers.get("origin")
    settings = request.app.state.settings
    if (origin is not None and origin not in settings.cors_origins) or (
        origin is None and request.headers.get("sec-fetch-site") == "cross-site"
    ):
        logger.warning("请求来源被拒绝", path=request.url.path)
        raise AppError(403, "csrf_origin_rejected", "请求来源不受信任")


@lru_cache
def get_login_rate_limiter() -> LoginRateLimiter:
    settings = get_settings()
    return LoginRateLimiter(
        max_failures=settings.auth_login_max_failures,
        window_seconds=settings.auth_login_window_seconds,
    )
