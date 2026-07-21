"""Pydantic 通用类型，供所有 schema 复用。"""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BeforeValidator, PlainSerializer


def _validate_utc_datetime(value: datetime) -> datetime:
    """确保 datetime 带时区信息。

    项目中所有 datetime 均通过 utc_now()（返回 datetime.now(UTC)）创建。
    若遇到 naive datetime（例如 SQLite 测试数据库因不支持时区而丢失 tzinfo），
    则按 UTC 处理——这与数据的语义意图一致。
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value


def _serialize_utc_datetime(value: datetime) -> str:
    """序列化为 ISO 8601 并以 Z 结尾（UTC）。"""
    utc_value = value.astimezone(UTC)
    return utc_value.isoformat().replace("+00:00", "Z")


UtcDateTime = Annotated[
    datetime,
    BeforeValidator(_validate_utc_datetime),
    PlainSerializer(_serialize_utc_datetime, return_type=str),
]
