from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import SessionDep, require_permission
from app.core.permissions import USERS_MANAGE
from app.models.user import User
from app.schemas.auth import (
    AdminPasswordReset,
    AdminUserCreate,
    AdminUserDetail,
    AdminUserUpdate,
    ChatLimitSnapshot,
    ChatLimitUpdate,
    SessionRevokeResult,
    UserPage,
)
from app.schemas.user import UserRead
from app.services.user_admin import (
    create_user,
    delete_user,
    list_users,
    read_chat_limit,
    reset_password,
    revoke_sessions,
    set_chat_limit,
    update_user,
    user_detail,
)

router = APIRouter(prefix="/admin/users", tags=["admin-users"])
AdminDep = Annotated[User, Depends(require_permission(USERS_MANAGE))]


@router.get("", response_model=UserPage)
def read_users(
    admin: AdminDep,
    session: SessionDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    q: Annotated[str | None, Query(max_length=100)] = None,
    role: Literal["admin", "member", "viewer"] | None = None,
    status: Literal["active", "disabled"] | None = None,
) -> UserPage:
    return list_users(session, offset=offset, limit=limit, q=q, role=role, status=status)


@router.get("/{user_id}", response_model=AdminUserDetail)
def read_user(user_id: UUID, admin: AdminDep, session: SessionDep) -> AdminUserDetail:
    return user_detail(session, user_id)


@router.get("/{user_id}/chat-limit", response_model=ChatLimitSnapshot)
def get_chat_limit(user_id: UUID, admin: AdminDep, session: SessionDep):
    return read_chat_limit(session, user_id)


@router.put("/{user_id}/chat-limit", response_model=ChatLimitSnapshot)
def put_chat_limit(user_id: UUID, payload: ChatLimitUpdate, admin: AdminDep, session: SessionDep):
    return set_chat_limit(session, admin, user_id, payload.hourly_limit)


@router.post("/{user_id}/revoke-sessions", response_model=SessionRevokeResult)
def post_revoke_sessions(user_id: UUID, admin: AdminDep, session: SessionDep):
    return SessionRevokeResult(revoked_count=revoke_sessions(session, admin, user_id))


@router.patch("/{user_id}", response_model=UserRead)
def patch_user(user_id: UUID, payload: AdminUserUpdate, admin: AdminDep, session: SessionDep):
    return UserRead.model_validate(
        update_user(session, admin, user_id, payload), from_attributes=True
    )


@router.post("", response_model=UserRead, status_code=201)
def post_user(payload: AdminUserCreate, admin: AdminDep, session: SessionDep):
    return UserRead.model_validate(create_user(session, admin, payload), from_attributes=True)


@router.post("/{user_id}/reset-password", status_code=204)
def post_reset_password(
    user_id: UUID, payload: AdminPasswordReset, admin: AdminDep, session: SessionDep
) -> Response:
    reset_password(session, admin, user_id, payload.new_password)
    return Response(status_code=204)


@router.delete("/{user_id}", status_code=204)
def remove_user(user_id: UUID, admin: AdminDep, session: SessionDep) -> Response:
    delete_user(session, admin, user_id)
    return Response(status_code=204)
