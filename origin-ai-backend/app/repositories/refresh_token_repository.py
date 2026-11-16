"""Refresh-session query and revocation operations."""

from datetime import datetime
from typing import Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db.models import RefreshToken


class RefreshTokenRepository:
    """Persistence operations for hashed refresh-token sessions."""

    @staticmethod
    def get_by_hash(
        db: Session,
        token_hash: str,
        *,
        lock: bool = False,
    ) -> Optional[RefreshToken]:
        query = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash)
        if lock:
            query = query.with_for_update()
        return query.first()

    @staticmethod
    def revoke_family(db: Session, family_id: str, revoked_at: datetime) -> int:
        result = db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.family_id == family_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )
        return result.rowcount or 0

    @staticmethod
    def revoke_user_sessions(db: Session, user_id: str, revoked_at: datetime) -> int:
        result = db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
        )
        return result.rowcount or 0


refresh_token_repository = RefreshTokenRepository()
