"""Authentication password and token primitives."""

import base64
import binascii
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import jwt
from cryptography.exceptions import InvalidKey
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from app.core.config import settings


_development_signing_key = secrets.token_bytes(64)
_ARGON2_MEMORY_COST_KIB = 64 * 1024
_ARGON2_ITERATIONS = 3
_ARGON2_LANES = 4
_ARGON2_HASH_LENGTH = 32


class InvalidAccessToken(ValueError):
    """Raised when an access token is malformed, invalid, or expired."""


def hash_password(password: str) -> str:
    """Hash a plaintext password with Argon2id and a random salt."""
    salt = secrets.token_bytes(16)
    digest = Argon2id(
        salt=salt,
        length=_ARGON2_HASH_LENGTH,
        iterations=_ARGON2_ITERATIONS,
        lanes=_ARGON2_LANES,
        memory_cost=_ARGON2_MEMORY_COST_KIB,
    ).derive(password.encode("utf-8"))
    encoded_salt = base64.b64encode(salt).decode("ascii").rstrip("=")
    encoded_digest = base64.b64encode(digest).decode("ascii").rstrip("=")
    return (
        f"$argon2id$v=19$m={_ARGON2_MEMORY_COST_KIB},"
        f"t={_ARGON2_ITERATIONS},p={_ARGON2_LANES}${encoded_salt}${encoded_digest}"
    )


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password without exposing verifier errors to callers."""
    try:
        prefix, algorithm, version, parameters, encoded_salt, encoded_digest = (
            password_hash.split("$")
        )
        if prefix or algorithm != "argon2id" or version != "v=19":
            return False
        parameter_values = {
            key: int(value)
            for key, value in (
                item.split("=", 1) for item in parameters.split(",")
            )
        }
        memory_cost = parameter_values["m"]
        iterations = parameter_values["t"]
        lanes = parameter_values["p"]
        if not (
            8 * 1024 <= memory_cost <= 256 * 1024
            and 1 <= iterations <= 10
            and 1 <= lanes <= 8
        ):
            return False
        salt = base64.b64decode(encoded_salt + "=" * (-len(encoded_salt) % 4))
        digest = base64.b64decode(encoded_digest + "=" * (-len(encoded_digest) % 4))
        Argon2id(
            salt=salt,
            length=len(digest),
            iterations=iterations,
            lanes=lanes,
            memory_cost=memory_cost,
        ).verify(password.encode("utf-8"), digest)
        return True
    except (InvalidKey, ValueError, TypeError, KeyError, binascii.Error):
        return False


_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-timing-equalization")


def verify_password_or_dummy(password: str, password_hash: str | None) -> bool:
    """Run a password hash check even when no eligible account exists."""
    return verify_password(password, password_hash or _DUMMY_PASSWORD_HASH)


def _signing_key() -> str | bytes:
    key = settings.JWT_SECRET_KEY
    if key:
        required_bytes = {"HS256": 32, "HS384": 48, "HS512": 64}[
            settings.JWT_ALGORITHM
        ]
        if len(key.encode("utf-8")) < required_bytes:
            raise RuntimeError("JWT_SECRET_KEY is too short for the configured algorithm.")
        return key
    if settings.ENVIRONMENT.casefold() in {"production", "prod"}:
        raise RuntimeError("JWT_SECRET_KEY must be configured in production.")
    return _development_signing_key


def create_access_token(user_id: str) -> tuple[str, int]:
    """Create a short-lived access JWT containing no personal profile data."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    claims = {
        "sub": user_id,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "iat": now,
        "exp": expires_at,
        "jti": secrets.token_urlsafe(16),
        "typ": "access",
    }
    token = jwt.encode(claims, _signing_key(), algorithm=settings.JWT_ALGORITHM)
    return token, settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


def decode_access_token(encoded_token: str) -> Dict[str, Any]:
    """Validate the configured signature, issuer, audience, expiry, and token type."""
    try:
        claims = jwt.decode(
            encoded_token,
            _signing_key(),
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
            options={
                "require": ["sub", "iss", "aud", "iat", "exp", "jti", "typ"],
            },
        )
        if claims.get("typ") != "access" or not isinstance(claims.get("sub"), str):
            raise InvalidAccessToken("Invalid access token.")
        return claims
    except (jwt.InvalidTokenError, TypeError, ValueError) as exc:
        raise InvalidAccessToken("Invalid access token.") from exc


def create_refresh_token() -> tuple[str, str]:
    """Return a high-entropy refresh token and its SHA-256 database digest."""
    token = secrets.token_urlsafe(48)
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> str:
    """Hash a raw refresh token before persistence or lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_token_matches(cookie_token: str | None, header_token: str | None) -> bool:
    """Compare double-submit CSRF values without timing-sensitive equality."""
    return bool(cookie_token and header_token) and hmac.compare_digest(
        cookie_token,
        header_token,
    )
