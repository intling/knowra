from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.user import UserRead
from app.services.users import CurrentUserUnavailableError, get_current_user

router = APIRouter(prefix="/users", tags=["users"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/me", response_model=UserRead)
def read_current_user(session: SessionDep) -> UserRead:
    try:
        user = get_current_user(session)
    except CurrentUserUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Current user is unavailable",
        ) from exc

    return UserRead.model_validate(user, from_attributes=True)
