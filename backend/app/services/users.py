from uuid import UUID

from sqlmodel import Session, select

from app.core.logging import get_logger
from app.models.user import User

logger = get_logger(__name__)

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
        logger.warning("当前用户不可用", default_user_id=str(DEFAULT_USER_ID))
        raise CurrentUserUnavailableError

    logger.debug("查询到当前用户", user_id=str(user.id))
    return user
