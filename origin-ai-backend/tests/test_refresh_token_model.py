from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import RefreshToken, User


def test_refresh_tokens_are_related_to_users_and_store_hashes_only():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user = User(email="session@example.com", full_name="Session User")
        token = RefreshToken(
            user=user,
            token_hash="a" * 64,
            family_id="family-id",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        session.add(token)
        session.commit()

        assert token.user_id == user.id
        assert user.refresh_tokens == [token]
        assert not hasattr(token, "token")

    engine.dispose()


def test_refresh_token_hash_is_unique():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user = User(email="unique@example.com", full_name="Unique User")
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        session.add_all(
            [
                RefreshToken(
                    user=user,
                    token_hash="b" * 64,
                    family_id="family-one",
                    expires_at=expires_at,
                ),
                RefreshToken(
                    user=user,
                    token_hash="b" * 64,
                    family_id="family-two",
                    expires_at=expires_at,
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()

    engine.dispose()
