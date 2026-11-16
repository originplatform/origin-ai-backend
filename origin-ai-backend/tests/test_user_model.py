from sqlalchemy import inspect
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import User


def test_user_model_includes_auth_fields_and_constraints():
    columns = User.__table__.columns

    assert {
        "id",
        "full_name",
        "email",
        "hashed_password",
        "profile_picture",
        "is_active",
        "is_verified",
        "auth_provider",
        "google_sub",
        "created_at",
        "updated_at",
    }.issubset(columns.keys())
    assert columns["email"].nullable is False
    assert columns["hashed_password"].nullable is True
    assert columns["google_sub"].nullable is True

    unique_columns = {
        index.columns[0].name
        for index in inspect(User).local_table.indexes
        if index.unique
    }
    assert {"email", "google_sub"}.issubset(unique_columns)


def test_legacy_name_attribute_aliases_full_name():
    user = User(email="person@example.com", name="Example Person")

    assert user.full_name == "Example Person"


def test_user_model_persists_provider_identity_and_defaults():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user = User(
            full_name="Google User",
            email="google@example.com",
            auth_provider="google",
            google_sub="google-subject-123",
        )
        session.add(user)
        session.commit()
        session.refresh(user)

        assert user.is_active is True
        assert user.is_verified is False
        assert user.hashed_password is None
        assert user.auth_provider == "google"
        assert user.google_sub == "google-subject-123"

    engine.dispose()
