from uuid import UUID

from sqlmodel import Session, select

from app.models.user import User

DEFAULT_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


class CurrentUserUnavailableError(Exception):
    pass


def get_current_user(session: Session) -> User:
    statement = select(User).where(
        User.id == DEFAULT_USER_ID,
        User.status == "active",
        User.deleted_at.is_(None),
    )
    user = session.exec(statement).first()

    if user is None:
        raise CurrentUserUnavailableError

    return user
