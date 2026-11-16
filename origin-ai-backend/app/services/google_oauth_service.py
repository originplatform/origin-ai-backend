"""Google OpenID Connect login and authenticated account linking."""

import asyncio
import base64
import hashlib
import secrets
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx
from google.auth.exceptions import GoogleAuthError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth_security import _signing_key
from app.core.config import settings
from app.db.models import User
from app.repositories.user_repository import user_repository


_GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_OAUTH_STATE_COOKIE = "origin_google_oauth"
_OAUTH_STATE_COOKIE_PATH = "/api/v1/auth/google/callback"


class GoogleOAuthError(Exception):
    """Base error for safe Google OAuth failure handling."""


class GoogleOAuthNotConfigured(GoogleOAuthError):
    """Raised when Google OAuth credentials are not configured."""


class GoogleIdentityError(GoogleOAuthError):
    """Raised when a Google identity response cannot be trusted."""


class GoogleAccountConflict(GoogleOAuthError):
    """Raised when identity must be explicitly linked to an existing account."""


class GoogleOAuthService:
    """Builds OIDC authorization requests and resolves verified Google identities."""

    oauth_state_cookie_name = _OAUTH_STATE_COOKIE
    oauth_state_cookie_path = _OAUTH_STATE_COOKIE_PATH

    @staticmethod
    def _require_configuration() -> None:
        if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
            raise GoogleOAuthNotConfigured

    @staticmethod
    def _serializer() -> URLSafeTimedSerializer:
        return URLSafeTimedSerializer(
            _signing_key(),
            salt="origin-ai-google-oauth-state-v1",
        )

    @classmethod
    def build_authorization_request(
        cls,
        *,
        link_user_id: Optional[str] = None,
    ) -> tuple[str, str]:
        cls._require_configuration()
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).decode("ascii").rstrip("=")
        signed_state = cls._serializer().dumps(
            {
                "state": state,
                "nonce": nonce,
                "verifier": verifier,
                "link_user_id": link_user_id,
            }
        )
        query = urlencode(
            {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "access_type": "online",
                "prompt": "select_account",
            }
        )
        return f"{_GOOGLE_AUTHORIZATION_ENDPOINT}?{query}", signed_state

    @classmethod
    def validate_state(cls, signed_state: str, returned_state: str) -> Dict[str, Any]:
        try:
            data = cls._serializer().loads(signed_state, max_age=600)
        except (BadSignature, SignatureExpired) as exc:
            raise GoogleIdentityError from exc
        expected_state = data.get("state")
        if not expected_state or not secrets.compare_digest(
            expected_state,
            returned_state,
        ):
            raise GoogleIdentityError
        if not data.get("nonce") or not data.get("verifier"):
            raise GoogleIdentityError
        return data

    @classmethod
    async def exchange_code(cls, code: str, verifier: str) -> str:
        cls._require_configuration()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    _GOOGLE_TOKEN_ENDPOINT,
                    data={
                        "code": code,
                        "client_id": settings.GOOGLE_CLIENT_ID,
                        "client_secret": settings.GOOGLE_CLIENT_SECRET,
                        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                        "grant_type": "authorization_code",
                        "code_verifier": verifier,
                    },
                )
                response.raise_for_status()
                token_response = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GoogleIdentityError from exc
        if not isinstance(token_response, dict):
            raise GoogleIdentityError
        id_token = token_response.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise GoogleIdentityError
        return id_token

    @staticmethod
    def _verify_id_token_sync(encoded_token: str) -> Dict[str, Any]:
        from google.auth.transport.requests import Request
        from google.oauth2 import id_token

        claims = id_token.verify_oauth2_token(
            encoded_token,
            Request(),
            settings.GOOGLE_CLIENT_ID,
        )
        if claims.get("iss") not in {
            "accounts.google.com",
            "https://accounts.google.com",
        }:
            raise GoogleIdentityError
        return claims

    @classmethod
    async def verify_id_token(
        cls,
        encoded_token: str,
        expected_nonce: str,
    ) -> Dict[str, Any]:
        try:
            claims = await asyncio.to_thread(cls._verify_id_token_sync, encoded_token)
        except (GoogleAuthError, ValueError) as exc:
            raise GoogleIdentityError from exc
        if not secrets.compare_digest(str(claims.get("nonce") or ""), expected_nonce):
            raise GoogleIdentityError
        if not claims.get("sub"):
            raise GoogleIdentityError
        if str(claims.get("email_verified", "")).casefold() not in {"true", "1"}:
            raise GoogleIdentityError
        if not claims.get("email"):
            raise GoogleIdentityError
        return claims

    @staticmethod
    def resolve_user(
        db: Session,
        claims: Dict[str, Any],
        *,
        link_user_id: Optional[str] = None,
    ) -> User:
        subject = str(claims["sub"])
        email = str(claims["email"]).strip().casefold()
        existing_subject = user_repository.get_by_google_sub(db, subject)

        if link_user_id:
            user = user_repository.get_by_id(db, link_user_id)
            if user is None or not user.is_active:
                raise GoogleAccountConflict
            if existing_subject and existing_subject.id != user.id:
                raise GoogleAccountConflict
            if user.google_sub and user.google_sub != subject:
                raise GoogleAccountConflict
            email_owner = user_repository.get_by_email(db, email)
            if email_owner and email_owner.id != user.id:
                raise GoogleAccountConflict
            user.google_sub = subject
            if user.email.casefold() == email:
                user.is_verified = True
            picture = claims.get("picture")
            if not user.profile_picture and isinstance(picture, str):
                if picture.startswith("https://"):
                    user.profile_picture = picture[:2048]
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise GoogleAccountConflict from exc
            return user

        if existing_subject:
            if not existing_subject.is_active:
                raise GoogleAccountConflict
            return existing_subject

        if user_repository.get_by_email(db, email):
            raise GoogleAccountConflict

        name = str(claims.get("name") or email.partition("@")[0]).strip()[:255]
        picture = claims.get("picture")
        user = User(
            full_name=name or email,
            email=email,
            is_active=True,
            is_verified=True,
            auth_provider="google",
            google_sub=subject,
            profile_picture=(
                picture[:2048]
                if isinstance(picture, str) and picture.startswith("https://")
                else None
            ),
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raced_subject = user_repository.get_by_google_sub(db, subject)
            if raced_subject and raced_subject.is_active:
                return raced_subject
            raise GoogleAccountConflict from exc
        db.refresh(user)
        return user


google_oauth_service = GoogleOAuthService()
