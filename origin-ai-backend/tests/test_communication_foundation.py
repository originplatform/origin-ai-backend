from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import Contact, GmailConnection, User
from app.core.config import settings
from app.services.gmail_service import gmail_service


def test_contact_model_and_repository_are_owner_scoped():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        owner = User(full_name="Owner One", email="owner@example.com")
        other = User(full_name="Owner Two", email="other@example.com")
        session.add_all([owner, other])
        session.commit()

        contact = Contact(
            owner_id=owner.id,
            full_name="Rahul Kumar",
            email_address="rahul@example.com",
            aliases=["rahul", "rk"],
            organization="Acme Labs",
            verification_status="verified",
        )
        session.add(contact)
        session.commit()

        assert session.query(Contact).filter(Contact.owner_id == owner.id).count() == 1
        assert session.query(Contact).filter(Contact.owner_id == other.id).count() == 0

        assert contact.email_address == "rahul@example.com"
        assert "rahul" in (contact.aliases or [])

    engine.dispose()


def test_gmail_connection_encrypts_tokens_and_tracks_status(monkeypatch):
    monkeypatch.setattr(settings, "GMAIL_ENCRYPTION_KEY", "test-gmail-encryption-key-for-unit-tests")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user = User(full_name="Owner One", email="owner@example.com")
        session.add(user)
        session.commit()

        connection = gmail_service.save_connection(
            session,
            user,
            email_address="owner@gmail.com",
            access_token="secret-access-token",
            refresh_token="secret-refresh-token",
            google_sub="google-123",
            scopes=["gmail.readonly", "gmail.send"],
        )

        assert connection.connection_status == "connected"
        assert connection.access_token_encrypted != "secret-access-token"
        assert gmail_service.decrypt(connection.access_token_encrypted) == "secret-access-token"
        assert gmail_service.get_access_token(session, user.id) == "secret-access-token"
        assert gmail_service.get_status_payload(session, user.id)["connected"] is True

    engine.dispose()
