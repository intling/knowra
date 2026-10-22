from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlmodel import Session

from app.api.deps import SessionDep, get_login_rate_limiter
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest
from app.schemas.user import UserRead
from app.services.auth import (
    SESSION_COOKIE,
    LoginRateLimiter,
    authenticate_user,
    create_session,
    register_user,
    revoke_session,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.auth_session_ttl_hours * 3600,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path=settings.api_prefix,
    )


def clear_session_cookie(response: Response, request: Request) -> None:
    settings = request.app.state.settings
    response.delete_cookie(
        SESSION_COOKIE,
        path=settings.api_prefix,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )


def start_session(response: Response, request: Request, session: Session, user: User) -> None:
    revoke_session(session, request.cookies.get(SESSION_COOKIE), commit=False)
    token = create_session(
        session, user, ttl=timedelta(hours=request.app.state.settings.auth_session_ttl_hours)
    )
    set_session_cookie(response, request, token)


@router.post("/register", response_model=UserRead, status_code=201)
def register(payload: RegisterRequest, request: Request, response: Response, session: SessionDep):
    user = register_user(session, **payload.model_dump())
    start_session(response, request, session, user)
    return UserRead.model_validate(user, from_attributes=True)


@router.post("/login", response_model=UserRead)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    limiter: Annotated[LoginRateLimiter, Depends(get_login_rate_limiter)],
):
    user = authenticate_user(session, limiter=limiter, **payload.model_dump())
    start_session(response, request, session, user)
    return UserRead.model_validate(user, from_attributes=True)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, session: SessionDep) -> None:
    revoke_session(session, request.cookies.get(SESSION_COOKIE))
    clear_session_cookie(response, request)
