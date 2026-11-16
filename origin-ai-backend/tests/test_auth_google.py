import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from google.oauth2 import id_token

from app.core.auth_security import hash_password
from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.models import User
from app.db.session import SessionLocal
from app.services.google_oauth_service import (
    GoogleIdentityError,
    GoogleOAuthService,
    google_oauth_service,
)


@pytest.fixture(autouse=True)
def reset_google_rate_limits(monkeypatch):
    limiter.reset()
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "test-google-client-id")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "test-google-client-secret")
    yield
    limiter.reset()


def _create_user(email=None):
    email = email or f"{uuid.uuid4().hex}@example.com"
    with SessionLocal() as db:
        user = User(
            full_name="Existing User",
            email=email,
            hashed_password=hash_password("Correct-Horse-Battery-42"),
            auth_provider="password",
        )
        db.add(user)
        db.commit()
        return user.id, email


def _start_google(client, *, link=False, access_token=None):
    headers = (
        {"Authorization": f"Bearer {access_token}"}
        if access_token
        else {}
    )
    route = "/api/v1/auth/google/link" if link else "/api/v1/auth/google"
    response = client.get(route, headers=headers, follow_redirects=False)
    query = parse_qs(urlparse(response.headers["location"]).query)
    return response, query["state"][0]


def _verified_claims(nonce, email=None, subject=None):
    return {
        "sub": subject or f"google-{uuid.uuid4().hex}",
        "email": email or f"{uuid.uuid4().hex}@example.com",
        "email_verified": True,
        "name": "Google Test User",
        "picture": "https://images.example.com/photo.png",
        "nonce": nonce,
    }


def test_google_login_start_requires_credentials(client, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "")

    response = client.get("/api/v1/auth/google")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "google_oauth_unavailable"


def test_google_oauth_link_requires_an_authenticated_user(client):
    response = client.get(
        "/api/v1/auth/google/link",
        follow_redirects=False,
    )

    assert response.status_code == 401


def test_google_login_start_uses_state_nonce_and_pkce(client):
    response, state = _start_google(client)
    query = parse_qs(urlparse(response.headers["location"]).query)
    oauth_cookie = response.cookies.get("origin_google_oauth")

    assert response.status_code == 302
    assert query["state"] == [state]
    assert query["scope"] == ["openid email profile"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["nonce"]
    assert oauth_cookie
    assert any("httponly" in value.casefold() for value in response.headers.get_list("set-cookie"))


def test_google_oidc_validation_uses_configured_audience(monkeypatch):
    def verify(encoded_token, request, audience):
        assert encoded_token == "signed-id-token"
        assert audience == settings.GOOGLE_CLIENT_ID
        return {"iss": "accounts.google.com", "sub": "google-subject"}

    monkeypatch.setattr(id_token, "verify_oauth2_token", verify)

    claims = google_oauth_service._verify_id_token_sync("signed-id-token")

    assert claims["sub"] == "google-subject"


@pytest.mark.asyncio
async def test_google_oidc_rejects_bad_nonce_and_unverified_email(monkeypatch):
    claims = {
        "sub": "google-subject",
        "email": "verified@example.com",
        "email_verified": True,
        "nonce": "expected-nonce",
    }
    monkeypatch.setattr(
        GoogleOAuthService,
        "_verify_id_token_sync",
        staticmethod(lambda encoded_token: claims),
    )

    assert (await google_oauth_service.verify_id_token("id-token", "expected-nonce"))[
        "sub"
    ] == "google-subject"
    with pytest.raises(GoogleIdentityError):
        await google_oauth_service.verify_id_token("id-token", "wrong-nonce")

    claims["email_verified"] = False
    with pytest.raises(GoogleIdentityError):
        await google_oauth_service.verify_id_token("id-token", "expected-nonce")


@pytest.mark.asyncio
async def test_google_oidc_maps_provider_verification_failures(monkeypatch):
    def reject_token(encoded_token):
        raise ValueError("provider rejected token")

    monkeypatch.setattr(
        GoogleOAuthService,
        "_verify_id_token_sync",
        staticmethod(reject_token),
    )

    with pytest.raises(GoogleIdentityError):
        await google_oauth_service.verify_id_token("invalid-token", "nonce")


def test_google_callback_creates_account_from_verified_identity(client, monkeypatch):
    async def exchange_code(code, verifier):
        assert code == "authorization-code"
        assert verifier
        return "mock-id-token"

    async def verify_id_token(encoded_token, nonce):
        assert encoded_token == "mock-id-token"
        return _verified_claims(nonce)

    monkeypatch.setattr(google_oauth_service, "exchange_code", exchange_code)
    monkeypatch.setattr(google_oauth_service, "verify_id_token", verify_id_token)
    start, state = _start_google(client)
    state_cookie = start.cookies.get("origin_google_oauth")
    signed_data = google_oauth_service.validate_state(state_cookie, state)

    callback = client.get(
        "/api/v1/auth/google/callback",
        params={"state": state, "code": "authorization-code"},
        follow_redirects=False,
    )

    assert callback.status_code == 303
    assert callback.headers["location"].endswith("?auth=success")
    assert callback.cookies.get("origin_refresh")
    assert callback.cookies.get("origin_csrf")
    with SessionLocal() as db:
        user = db.query(User).filter(User.google_sub.is_not(None)).one()
        assert user.google_sub.startswith("google-")
        assert user.email.endswith("@example.com")
        assert user.is_verified is True
        assert user.hashed_password is None
        assert signed_data["nonce"]


def test_google_login_does_not_auto_link_an_existing_email(client, monkeypatch):
    _, email = _create_user()

    async def exchange_code(code, verifier):
        return "mock-id-token"

    async def verify_id_token(encoded_token, nonce):
        return _verified_claims(nonce, email=email)

    monkeypatch.setattr(google_oauth_service, "exchange_code", exchange_code)
    monkeypatch.setattr(google_oauth_service, "verify_id_token", verify_id_token)
    start, state = _start_google(client)

    callback = client.get(
        "/api/v1/auth/google/callback",
        params={"state": state, "code": "authorization-code"},
        follow_redirects=False,
    )

    assert callback.headers["location"].endswith("?auth=account_conflict")
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).one()
        assert user.google_sub is None


def test_google_link_requires_authenticated_user_and_links_explicitly(client, monkeypatch):
    user_id, email = _create_user()
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Correct-Horse-Battery-42"},
    )
    access_token = login.json()["access_token"]
    start, state = _start_google(client, link=True, access_token=access_token)
    signed_data = google_oauth_service.validate_state(
        start.cookies.get("origin_google_oauth"),
        state,
    )

    async def exchange_code(code, verifier):
        return "mock-id-token"

    async def verify_id_token(encoded_token, nonce):
        return _verified_claims(nonce, email="different@example.com")

    monkeypatch.setattr(google_oauth_service, "exchange_code", exchange_code)
    monkeypatch.setattr(google_oauth_service, "verify_id_token", verify_id_token)
    callback = client.get(
        "/api/v1/auth/google/callback",
        params={"state": state, "code": "authorization-code"},
        follow_redirects=False,
    )

    assert signed_data["link_user_id"] == user_id
    assert callback.headers["location"].endswith("?auth=success")
    with SessionLocal() as db:
        linked_user = db.query(User).filter(User.id == user_id).one()
        assert linked_user.google_sub.startswith("google-")
        assert linked_user.email == email
        assert linked_user.auth_provider == "password"


def test_google_callback_rejects_state_mismatch_and_cancelled_authorization(client):
    start, state = _start_google(client)
    cookie = start.cookies.get("origin_google_oauth")

    mismatch = client.get(
        "/api/v1/auth/google/callback",
        params={"state": "not-the-returned-state", "code": "code"},
        follow_redirects=False,
    )
    client.cookies.set(
        "origin_google_oauth",
        cookie,
        path="/api/v1/auth/google/callback",
    )
    cancelled = client.get(
        "/api/v1/auth/google/callback",
        params={"state": state, "error": "access_denied"},
        follow_redirects=False,
    )

    assert mismatch.headers["location"].endswith("?auth=google_auth_failed")
    assert cancelled.headers["location"].endswith("?auth=google_auth_failed")
