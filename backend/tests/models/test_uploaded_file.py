from datetime import UTC, datetime
from importlib import import_module

import pytest
from sqlalchemy import UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.user import User

REQUIRED_COLUMNS = {
    "id",
    "owner_user_id",
    "original_filename",
    "content_type",
    "byte_size",
    "storage_key",
    "checksum_sha256",
    "status",
    "error_message",
    "deleted_at",
    "created_at",
    "updated_at",
}


def get_uploaded_file_model():
    return import_module("app.models.uploaded_file").UploadedFile


def has_unique_storage_key_constraint(uploaded_file_model) -> bool:
    table = uploaded_file_model.__table__
    storage_key = table.columns["storage_key"]
    if storage_key.unique:
        return True

    return any(
        isinstance(constraint, UniqueConstraint)
        and {column.name for column in constraint.columns} == {"storage_key"}
        for constraint in table.constraints
    )


# 测试 SQLModel 表结构契约：必需字段、当前用户外键、
# storage_key 唯一约束，以及后续上传流程需要的查询索引。
def test_uploaded_file_table_contract() -> None:
    UploadedFile = get_uploaded_file_model()
    table = UploadedFile.__table__
    columns = table.columns

    assert set(columns.keys()) == REQUIRED_COLUMNS
    assert columns["id"].primary_key
    assert not columns["owner_user_id"].nullable
    assert not columns["original_filename"].nullable
    assert not columns["byte_size"].nullable
    assert not columns["storage_key"].nullable
    assert not columns["status"].nullable
    assert columns["content_type"].nullable
    assert columns["error_message"].nullable
    assert columns["deleted_at"].nullable

    foreign_targets = {
        foreign_key.target_fullname for foreign_key in columns["owner_user_id"].foreign_keys
    }
    assert foreign_targets == {"users.id"}
    assert has_unique_storage_key_constraint(UploadedFile)

    indexed_columns = {column.name for index in table.indexes for column in index.columns}
    assert {"owner_user_id", "status", "created_at"} <= indexed_columns


# 测试数据库会拒绝重复的应用内 storage_key，
# 避免多个成功上传记录指向同一个存储对象。
def test_uploaded_file_storage_key_is_unique() -> None:
    UploadedFile = get_uploaded_file_model()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    created_at = datetime(2026, 5, 25, tzinfo=UTC)

    with Session(engine) as session:
        user = User(display_name="Upload Owner")
        session.add(user)
        session.commit()
        session.refresh(user)

        session.add(
            UploadedFile(
                owner_user_id=user.id,
                original_filename="first.txt",
                content_type="text/plain",
                byte_size=5,
                storage_key="uploads/user/upload/original.txt",
                checksum_sha256="a" * 64,
                status="stored",
                created_at=created_at,
                updated_at=created_at,
            )
        )
        session.commit()

        session.add(
            UploadedFile(
                owner_user_id=user.id,
                original_filename="second.txt",
                content_type="text/plain",
                byte_size=6,
                storage_key="uploads/user/upload/original.txt",
                checksum_sha256="b" * 64,
                status="stored",
                created_at=created_at,
                updated_at=created_at,
            )
        )

        with pytest.raises(IntegrityError):
            session.commit()
