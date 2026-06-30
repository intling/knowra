from sqlmodel import SQLModel

from app.core.logging import get_logger
from app.db.session import engine

logger = get_logger(__name__)


def init_db() -> None:
    logger.info("开始创建数据库表")
    SQLModel.metadata.create_all(engine)
    logger.info("数据库表创建完成")
