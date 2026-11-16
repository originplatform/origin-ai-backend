"""User lookup and persistence operations."""

from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import User


class UserRepository:
    """Small user data-access layer shared by auth and profile services."""

    @staticmethod
    def get_by_id(db: Session, user_id: str) -> Optional[User]:
        return db.query(User).filter(User.id == user_id).first()

    @staticmethod
    def get_by_email(db: Session, email: str) -> Optional[User]:
        normalized_email = email.strip().casefold()
        return (
            db.query(User)
            .filter(func.lower(User.email) == normalized_email)
            .first()
        )

    @staticmethod
    def get_by_google_sub(db: Session, google_sub: str) -> Optional[User]:
        return db.query(User).filter(User.google_sub == google_sub).first()


user_repository = UserRepository()
