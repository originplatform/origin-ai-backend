"""Reusable authentication and authorization dependencies."""

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.auth_security import InvalidAccessToken, decode_access_token
from app.db.models import User
from app.db.session import get_db
from app.repositories.user_repository import user_repository


_bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "unauthorized", "message": "Authentication is required."},
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> Optional[User]:
    if credentials is None:
        return None
    if credentials.scheme.casefold() != "bearer":
        raise _unauthorized()
    try:
        claims = decode_access_token(credentials.credentials)
    except InvalidAccessToken:
        raise _unauthorized()
    user = user_repository.get_by_id(db, claims["sub"])
    if user is None or not user.is_active:
        raise _unauthorized()
    return user


def get_current_user(
    user: Optional[User] = Depends(get_optional_current_user),
) -> User:
    if user is None:
        raise _unauthorized()
    return user


def require_active_user(user: User = Depends(get_current_user)) -> User:
    return user


def require_verified_user(user: User = Depends(get_current_user)) -> User:
    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "verification_required", "message": "Verify your account first."},
        )
    return user
