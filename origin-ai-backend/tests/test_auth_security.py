from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.auth_security import (
    InvalidAccessToken,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.core.config import Settings, settings


def test_argon2id_password_hash_round_trip():
    encoded = hash_password("a sufficiently long password")

    assert encoded.startswith("$argon2id$")
    assert encoded != "a sufficiently long password"
    assert verify_password("a sufficiently long password", encoded)
    assert not verify_password("a different sufficiently long password", encoded)
    assert not verify_password("password", "malformed")


def test_jwt_contains_required_claims_and_round_trips(monkeypatch):
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "s" * 64)
    token, expires_in = create_access_token("user-123")

    claims = decode_access_token(token)

    assert claims["sub"] == "user-123"
    assert claims["iss"] == settings.JWT_ISSUER
    assert claims["aud"] == settings.JWT_AUDIENCE
    assert claims["typ"] == "access"
    assert claims["jti"]
    assert expires_in == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert "email" not in claims


@pytest.mark.parametrize(
    "claims",
    [
        {"sub": "u", "iss": "wrong", "aud": "origin-ai-client", "typ": "access"},
        {"sub": "u", "iss": "origin-ai", "aud": "wrong", "typ": "access"},
        {"sub": "u", "iss": "origin-ai", "aud": "origin-ai-client", "typ": "refresh"},
    ],
)
def test_jwt_rejects_wrong_issuer_audience_or_token_type(monkeypatch, claims):
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "s" * 64)
    now = datetime.now(timezone.utc)
    payload = {
        **claims,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "jti": "token-id",
    }
    token = jwt.encode(payload, "s" * 64, algorithm="HS256")

    with pytest.raises(InvalidAccessToken):
        decode_access_token(token)


def test_jwt_rejects_expired_malformed_and_wrong_signature(monkeypatch):
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "s" * 64)
    now = datetime.now(timezone.utc)
    expired = jwt.encode(
        {
            "sub": "u",
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
            "typ": "access",
            "iat": now - timedelta(minutes=2),
            "exp": now - timedelta(minutes=1),
            "jti": "expired",
        },
        "s" * 64,
        algorithm="HS256",
    )
    wrong_signature = jwt.encode(
        {
            "sub": "u",
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
            "typ": "access",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "jti": "wrong-signature",
        },
        "x" * 64,
        algorithm="HS256",
    )

    for token in (expired, wrong_signature, "malformed"):
        with pytest.raises(InvalidAccessToken):
            decode_access_token(token)


def test_production_settings_require_strong_key_and_secure_cookie():
    with pytest.raises(ValueError, match="strong JWT_SECRET_KEY"):
        Settings(ENVIRONMENT="production", JWT_SECRET_KEY="", COOKIE_SECURE=True)

    with pytest.raises(ValueError, match="COOKIE_SECURE=true"):
        Settings(
            ENVIRONMENT="production",
            JWT_SECRET_KEY="s" * 32,
            COOKIE_SECURE=False,
            CORS_ORIGINS=["https://frontend.example"],
            FRONTEND_URL="https://frontend.example",
            GOOGLE_REDIRECT_URI="https://api.example/api/v1/auth/google/callback",
        )

    Settings(
        ENVIRONMENT="production",
        JWT_SECRET_KEY="s" * 32,
        COOKIE_SECURE=True,
        CORS_ORIGINS=["https://frontend.example"],
        FRONTEND_URL="https://frontend.example",
        GOOGLE_REDIRECT_URI="https://api.example/api/v1/auth/google/callback",
    )


def test_credentialed_cors_rejects_wildcard_origins():
    with pytest.raises(ValueError, match="Wildcard CORS"):
        Settings(CORS_ORIGINS=["*"])


def test_csrf_double_submit_values_are_required_and_compared():
    from app.core.auth_security import csrf_token_matches

    assert csrf_token_matches("value", "value")
    assert not csrf_token_matches("value", "different")
    assert not csrf_token_matches("value", None)
