"""Access-token creation and refresh-session lifecycle."""

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.auth_security import (
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
)
from app.core.config import settings
from app.db.models import RefreshToken, User
from app.repositories.refresh_token_repository import refresh_token_repository
from app.repositories.user_repository import user_repository


class InvalidRefreshToken(Exception):
    """Raised when a refresh token is expired, revoked, or unavailable."""


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    expires_in: int
    refresh_token: str
    csrf_token: str
    user: User


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class TokenService:
    """Issues short-lived access JWTs and rotates hashed refresh sessions."""

    @staticmethod
    def _new_refresh_record(
        *,
        token_id: str,
        user_id: str,
        token_hash: str,
        family_id: str,
        expires_at: datetime,
        device_name: Optional[str],
    ) -> RefreshToken:
        return RefreshToken(
            id=token_id,
            user_id=user_id,
            token_hash=token_hash,
            family_id=family_id,
            expires_at=expires_at,
            device_name=device_name,
        )

    @staticmethod
    def issue_session(
        db: Session,
        user: User,
        device_name: Optional[str] = None,
    ) -> IssuedTokens:
        access_token, expires_in = create_access_token(user.id)
        raw_refresh_token, refresh_token_hash = create_refresh_token()
        now = datetime.now(timezone.utc)
        db.add(
            TokenService._new_refresh_record(
                token_id=str(uuid.uuid4()),
                user_id=user.id,
                token_hash=refresh_token_hash,
                family_id=str(uuid.uuid4()),
                expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
                device_name=device_name[:255] if device_name else None,
            )
        )
        csrf_token = secrets.token_urlsafe(32)
        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            raise
        return IssuedTokens(
            access_token=access_token,
            expires_in=expires_in,
            refresh_token=raw_refresh_token,
            csrf_token=csrf_token,
            user=user,
        )

    @staticmethod
    def rotate(db: Session, raw_token: str) -> IssuedTokens:
        now = datetime.now(timezone.utc)
        token_hash = hash_refresh_token(raw_token)
        current = refresh_token_repository.get_by_hash(db, token_hash, lock=True)
        if current is None:
            raise InvalidRefreshToken

        if current.revoked_at is not None:
            if current.replaced_by_token_id:
                refresh_token_repository.revoke_family(db, current.family_id, now)
                db.commit()
            raise InvalidRefreshToken

        if _utc(current.expires_at) <= now:
            current.revoked_at = now
            db.commit()
            raise InvalidRefreshToken

        user = user_repository.get_by_id(db, current.user_id)
        if user is None or not user.is_active:
            current.revoked_at = now
            db.commit()
            raise InvalidRefreshToken

        new_raw_token, new_token_hash = create_refresh_token()
        new_token_id = str(uuid.uuid4())
        access_token, expires_in = create_access_token(user.id)
        csrf_token = secrets.token_urlsafe(32)

        db.add(
            TokenService._new_refresh_record(
                token_id=new_token_id,
                user_id=user.id,
                token_hash=new_token_hash,
                family_id=current.family_id,
                expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
                device_name=current.device_name,
            )
        )
        db.flush()

        try:
            update_result = db.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.id == current.id,
                    RefreshToken.revoked_at.is_(None),
                    RefreshToken.expires_at > now,
                )
                .values(
                    revoked_at=now,
                    replaced_by_token_id=new_token_id,
                )
                .execution_options(synchronize_session=False)
            )
        except SQLAlchemyError as exc:
            db.rollback()
            try:
                raced_token = refresh_token_repository.get_by_hash(db, token_hash)
                if raced_token and raced_token.replaced_by_token_id:
                    refresh_token_repository.revoke_family(
                        db,
                        raced_token.family_id,
                        now,
                    )
                    db.commit()
            except SQLAlchemyError:
                db.rollback()
            raise InvalidRefreshToken from exc
        if update_result.rowcount != 1:
            db.rollback()
            raced_token = refresh_token_repository.get_by_hash(db, token_hash)
            if raced_token and raced_token.replaced_by_token_id:
                refresh_token_repository.revoke_family(db, raced_token.family_id, now)
                db.commit()
            raise InvalidRefreshToken
        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            raise

        return IssuedTokens(
            access_token=access_token,
            expires_in=expires_in,
            refresh_token=new_raw_token,
            csrf_token=csrf_token,
            user=user,
        )

    @staticmethod
    def revoke_session(
        db: Session,
        raw_token: str,
        user_id: str,
    ) -> bool:
        session = refresh_token_repository.get_by_hash(
            db,
            hash_refresh_token(raw_token),
        )
        if session is None or session.user_id != user_id or session.revoked_at:
            return False
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()
        return True

    @staticmethod
    def revoke_all_sessions(db: Session, user_id: str) -> int:
        count = refresh_token_repository.revoke_user_sessions(
            db,
            user_id,
            datetime.now(timezone.utc),
        )
        db.commit()
        return count


token_service = TokenService()
