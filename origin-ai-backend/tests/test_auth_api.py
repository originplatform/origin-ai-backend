import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from app.core.auth_security import hash_password, hash_refresh_token
from app.core.rate_limit import limiter
from app.db.models import RefreshToken, User
from app.db.session import SessionLocal
from app.services.token_service import InvalidRefreshToken, token_service


@pytest.fixture(autouse=True)
def reset_auth_rate_limits():
    limiter.reset()
    yield
    limiter.reset()


def _create_user(
    email=None,
    password="Correct-Horse-Battery-42",
    *,
    active=True,
):
    email = email or f"{uuid.uuid4().hex}@example.com"
    with SessionLocal() as db:
        user = User(
            full_name="Test Member",
            email=email,
            hashed_password=hash_password(password),
            auth_provider="password",
            is_active=active,
        )
        db.add(user)
        db.commit()
        return user.id, email


def _login(client, email="member@example.com", password="Correct-Horse-Battery-42"):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )


def test_registration_normalizes_email_hashes_password_and_returns_safe_user(client):
    email = f"{uuid.uuid4().hex}@example.com"
    response = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "  Test Member ",
            "email": f" {email.upper()} ",
            "password": "Correct-Horse-Battery-42",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["full_name"] == "Test Member"
    assert body["email"] == email
    assert body["auth_provider"] == "password"
    assert body["is_verified"] is False
    assert "hashed_password" not in body
    with SessionLocal() as db:
        stored_user = db.query(User).filter(User.email == email).one()
        assert stored_user.hashed_password.startswith("$argon2id$")
        assert stored_user.hashed_password != "Correct-Horse-Battery-42"


def test_registration_rejects_duplicate_normalized_email_and_bad_inputs(client):
    email = f"{uuid.uuid4().hex}@example.com"
    first = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Test Member",
            "email": email,
            "password": "Correct-Horse-Battery-42",
        },
    )
    duplicate = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Another Member",
            "email": email.upper(),
            "password": "Another-Correct-Password-43",
        },
    )
    invalid_email = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Bad Email",
            "email": "not-an-email",
            "password": "Correct-Horse-Battery-42",
        },
    )
    weak_password = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Weak Password",
            "email": "weak@example.com",
            "password": "short",
        },
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert invalid_email.status_code == 422
    assert weak_password.status_code == 422
    assert duplicate.json()["detail"]["code"] == "account_exists"


def test_login_is_generic_and_issues_access_and_refresh_cookies(client):
    _, email = _create_user()
    response = _login(client, email=email)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    assert body["user"]["email"] == email
    assert "hashed_password" not in body["user"]
    assert "refresh_token" not in body
    assert response.cookies.get("origin_refresh")
    assert response.cookies.get("origin_csrf") == body["csrf_token"]
    cookies = response.headers.get_list("set-cookie")
    refresh_cookie = next(
        cookie
        for cookie in cookies
        if cookie.startswith("origin_refresh=")
    )
    assert "httponly" in refresh_cookie.casefold()
    csrf_cookie = next(cookie for cookie in cookies if cookie.startswith("origin_csrf="))
    assert "httponly" in csrf_cookie.casefold()

    current = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert current.status_code == 200
    assert current.json()["id"] == body["user"]["id"]
    assert client.get("/api/v1/auth/csrf").json()["csrf_token"] == body["csrf_token"]


def test_invalid_unknown_and_inactive_login_credentials_are_indistinguishable(client):
    _, email = _create_user()
    _, inactive_email = _create_user(
        email=f"{uuid.uuid4().hex}@example.com",
        active=False,
    )

    wrong_password = _login(
        client,
        email=email,
        password="Wrong-Correct-Password-42",
    )
    unknown_email = _login(client, email=f"unknown-{uuid.uuid4().hex}@example.com")
    inactive_user = _login(client, email=inactive_email)

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json() == inactive_user.json()


def test_refresh_rotates_tokens_and_reuse_revokes_the_token_family(client):
    _, email = _create_user()
    login_response = _login(client, email=email)
    old_refresh = login_response.cookies.get("origin_refresh")
    old_csrf = login_response.cookies.get("origin_csrf")

    rotated = client.post(
        "/api/v1/auth/refresh",
        headers={"X-CSRF-Token": old_csrf},
    )
    assert rotated.status_code == 200
    new_refresh = rotated.cookies.get("origin_refresh")
    new_csrf = rotated.cookies.get("origin_csrf")
    assert new_refresh and new_refresh != old_refresh

    replay = client.post(
        "/api/v1/auth/refresh",
        headers={
            "Cookie": f"origin_refresh={old_refresh}; origin_csrf={new_csrf}",
            "X-CSRF-Token": new_csrf,
        },
    )
    assert replay.status_code == 401

    after_reuse = client.post(
        "/api/v1/auth/refresh",
        headers={
            "Cookie": f"origin_refresh={new_refresh}; origin_csrf={new_csrf}",
            "X-CSRF-Token": new_csrf,
        },
    )
    assert after_reuse.status_code == 401


def test_refresh_rejects_expired_sessions_and_disabled_users(client):
    _, email = _create_user()
    login_response = _login(client, email=email)
    raw_token = login_response.cookies.get("origin_refresh")
    token_hash = hash_refresh_token(raw_token)

    with SessionLocal() as db:
        stored = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).one()
        stored.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    expired = client.post(
        "/api/v1/auth/refresh",
        headers={"X-CSRF-Token": login_response.cookies.get("origin_csrf")},
    )
    assert expired.status_code == 401

    _, inactive_email = _create_user()
    inactive_login = _login(client, email=inactive_email)
    inactive_raw = inactive_login.cookies.get("origin_refresh")
    with SessionLocal() as db:
        inactive_user = db.query(User).filter(User.email == inactive_email).one()
        inactive_user.is_active = False
        db.commit()
    inactive = client.post(
        "/api/v1/auth/refresh",
        headers={"X-CSRF-Token": inactive_login.cookies.get("origin_csrf")},
    )
    assert inactive.status_code == 401
    with SessionLocal() as db:
        inactive_session = (
            db.query(RefreshToken)
            .filter(RefreshToken.token_hash == hash_refresh_token(inactive_raw))
            .one()
        )
        assert inactive_session.revoked_at is not None


def test_concurrent_refresh_attempts_cannot_both_rotate_the_same_session(client):
    _, email = _create_user()
    login_response = _login(client, email=email)
    raw_token = login_response.cookies.get("origin_refresh")
    barrier = Barrier(2)

    def rotate():
        with SessionLocal() as db:
            barrier.wait(timeout=5)
            try:
                token_service.rotate(db, raw_token)
                return "rotated"
            except InvalidRefreshToken:
                return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: rotate(), range(2)))

    assert sorted(results) == ["rejected", "rotated"]


def test_refresh_requires_csrf_and_logout_revokes_the_session(client):
    _, email = _create_user()
    login_response = _login(client, email=email)
    access_token = login_response.json()["access_token"]
    raw_refresh = login_response.cookies.get("origin_refresh")

    missing_csrf = client.post("/api/v1/auth/refresh")
    assert missing_csrf.status_code == 403

    logout_response = client.post(
        "/api/v1/auth/logout",
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-CSRF-Token": login_response.cookies.get("origin_csrf"),
        },
    )
    assert logout_response.status_code == 204
    client.cookies.set("origin_refresh", raw_refresh, path="/api/v1/auth")
    client.cookies.set(
        "origin_csrf",
        login_response.cookies.get("origin_csrf"),
        path="/api/v1/auth",
    )
    revoked_refresh = client.post(
        "/api/v1/auth/refresh",
        headers={"X-CSRF-Token": login_response.cookies.get("origin_csrf")},
    )
    assert revoked_refresh.status_code == 401


def test_logout_all_revokes_every_session_for_the_user(client):
    user_id, email = _create_user()
    _login(client, email=email)
    second = _login(client, email=email)

    logout_all = client.post(
        "/api/v1/auth/logout-all",
        headers={"Authorization": f"Bearer {second.json()['access_token']}"},
    )
    assert logout_all.status_code == 204
    assert client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {second.json()['access_token']}"},
    ).status_code == 200
    with SessionLocal() as db:
        sessions = db.query(RefreshToken).filter(RefreshToken.user_id == user_id).all()
        assert len(sessions) == 2
        assert all(session.revoked_at is not None for session in sessions)


def test_authentication_and_profile_routes_reject_missing_and_invalid_tokens(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer malformed"},
    ).status_code == 401


def test_profile_update_allows_only_self_editable_fields(client):
    _, email = _create_user()
    login_response = _login(client, email=email)
    headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

    updated = client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={
            "full_name": "Updated Name",
            "profile_picture": "https://images.example.com/avatar.png",
        },
    )
    forbidden = client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"is_active": False, "is_verified": True},
    )
    assert updated.status_code == 200
    assert updated.json()["full_name"] == "Updated Name"
    assert updated.json()["profile_picture"] == "https://images.example.com/avatar.png"
    assert forbidden.status_code == 422


def test_login_rate_limit_is_enforced(client):
    responses = [
        _login(client, email="not-found@example.com")
        for _ in range(6)
    ]

    assert [response.status_code for response in responses[:5]] == [401] * 5
    assert responses[5].status_code == 429
    assert responses[5].json()["detail"]["code"] == "rate_limit_exceeded"


def test_registration_rate_limit_is_enforced(client):
    responses = [
        client.post(
            "/api/v1/auth/register",
            json={
                "full_name": "Rate Limited User",
                "email": f"{uuid.uuid4().hex}@example.com",
                "password": "Correct-Horse-Battery-42",
            },
        )
        for _ in range(6)
    ]

    assert [response.status_code for response in responses[:5]] == [201] * 5
    assert responses[5].status_code == 429
