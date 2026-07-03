import re
from collections.abc import Generator

from sqlmodel import Session, create_engine

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

settings = get_settings()
engine = create_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
)

# Desensitize password in database URL for logging.
_desensitized_url = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", settings.database_url)
logger.info("数据库引擎已创建", database_url=_desensitized_url, echo=settings.debug)


def get_session() -> Generator[Session]:
    with Session(engine) as session:
        yield session
