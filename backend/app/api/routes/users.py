from fastapi import APIRouter, Request, Response

from app.api.deps import CurrentUserDep, SessionDep
from app.api.routes.auth import clear_session_cookie
from app.schemas.auth import PasswordChange, ProfileUpdate
from app.schemas.user import UserRead
from app.services.auth import change_password, update_profile

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
def read_current_user(user: CurrentUserDep) -> UserRead:
    return UserRead.model_validate(user, from_attributes=True)


@router.patch("/me", response_model=UserRead)
def patch_current_user(
    payload: ProfileUpdate, user: CurrentUserDep, session: SessionDep
) -> UserRead:
    updated = update_profile(session, user, payload.display_name)
    return UserRead.model_validate(updated, from_attributes=True)


@router.post("/me/password", status_code=204)
def post_password(
    payload: PasswordChange,
    user: CurrentUserDep,
    session: SessionDep,
    request: Request,
    response: Response,
) -> None:
    change_password(session, user, **payload.model_dump())
    clear_session_cookie(response, request)
