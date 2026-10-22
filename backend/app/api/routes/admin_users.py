from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import SessionDep, require_permission
from app.core.permissions import USERS_MANAGE
from app.models.user import User
from app.schemas.auth import AdminPasswordReset, AdminUserCreate, AdminUserUpdate, UserPage
from app.schemas.user import UserRead
from app.services.user_admin import (
    create_user,
    delete_user,
    list_users,
    reset_password,
    update_user,
)

router = APIRouter(prefix="/admin/users", tags=["admin-users"])
AdminDep = Annotated[User, Depends(require_permission(USERS_MANAGE))]


@router.get("", response_model=UserPage)
def read_users(
    admin: AdminDep,
    session: SessionDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> UserPage:
    return list_users(session, offset=offset, limit=limit)


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
