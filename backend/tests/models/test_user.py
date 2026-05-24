import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.models.user import User


def test_user_table_contains_required_columns() -> None:
    columns = User.__table__.columns

    assert set(columns.keys()) == {
        "id",
        "display_name",
        "email",
        "avatar_url",
        "status",
        "deleted_at",
        "created_at",
        "updated_at",
    }
    assert columns["id"].primary_key
    assert not columns["display_name"].nullable
    assert not columns["status"].nullable
    assert columns["deleted_at"].nullable


def test_user_email_allows_multiple_nulls_and_rejects_duplicate_non_null_values() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(User(display_name="First User"))
        session.add(User(display_name="Second User"))
        session.commit()

        session.add(User(display_name="Third User", email="user@example.com"))
        session.commit()

        session.add(User(display_name="Fourth User", email="user@example.com"))

        with pytest.raises(IntegrityError):
            session.commit()
