"""Registration and password authentication business logic."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth_security import hash_password, verify_password_or_dummy
from app.db.models import User
from app.repositories.user_repository import user_repository
from app.schemas.auth import RegisterRequest


class DuplicateUserError(Exception):
    """Raised when an account already exists for a normalized email."""


class AuthService:
    """User registration and credential verification."""

    @staticmethod
    def register(db: Session, payload: RegisterRequest) -> User:
        normalized_email = str(payload.email).strip().casefold()
        if user_repository.get_by_email(db, normalized_email):
            raise DuplicateUserError

        user = User(
            full_name=payload.full_name,
            email=normalized_email,
            hashed_password=hash_password(payload.password),
            auth_provider="password",
            is_verified=False,
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            if user_repository.get_by_email(db, normalized_email):
                raise DuplicateUserError from exc
            raise
        db.refresh(user)
        return user

    @staticmethod
    def authenticate(db: Session, email: str, password: str) -> User | None:
        user = user_repository.get_by_email(db, email)
        password_matches = verify_password_or_dummy(
            password,
            user.hashed_password if user else None,
        )
        if (
            user is None
            or not user.is_active
            or not user.hashed_password
            or not password_matches
        ):
            return None
        return user


auth_service = AuthService()
