import asyncio
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.core.config import settings
from app.db.models import GmailConnection, User
from app.db.session import SessionLocal
from app.services.gmail_service import GmailService, GmailServiceError, gmail_service


def _register_and_login(client):
    email = f"{uuid.uuid4().hex}@example.com"
    password = "Correct-Horse-Battery-42"
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Gmail Owner",
            "email": email,
            "password": password,
        },
    )
    assert registration.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200
    return registration.json()["id"], login.json()["access_token"]


def _json_response(url, payload, status_code=200):
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("GET", url),
    )


def _insert_user(email=None):
    with SessionLocal() as db:
        user = User(
            full_name="Gmail Test Owner",
            email=email or f"{uuid.uuid4().hex}@example.com",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id


@pytest.fixture
def gmail_settings(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "client-id.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(
        settings,
        "GOOGLE_GMAIL_REDIRECT_URI",
        "http://localhost:8000/api/v1/communication/gmail/callback",
    )
    monkeypatch.setattr(settings, "GMAIL_ENCRYPTION_KEY", "test-gmail-encryption-key-for-unit-tests")


def test_gmail_oauth_start_requires_auth_and_requests_read_only_scope(
    client,
    gmail_settings,
):
    unauthorized = client.get("/api/v1/communication/gmail/connect/start")
    assert unauthorized.status_code == 401

    owner_id, access_token = _register_and_login(client)
    response = client.get(
        "/api/v1/communication/gmail/connect/start",
        headers={"Authorization": f"Bearer {access_token}"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["client_id"] == ["client-id.apps.googleusercontent.com"]
    assert query["redirect_uri"] == [settings.GOOGLE_GMAIL_REDIRECT_URI]
    assert "https://www.googleapis.com/auth/gmail.readonly" in query["scope"][0]
    assert "gmail.send" not in query["scope"][0]
    assert "gmail.modify" not in query["scope"][0]
    assert query["access_type"] == ["offline"]
    assert response.cookies.get(gmail_service.oauth_cookie_name())
    assert owner_id


def test_gmail_oauth_state_rejects_missing_invalid_and_wrong_owner(gmail_settings):
    owner_id = str(uuid.uuid4())
    auth_url, signed_state = gmail_service.build_authorization_request(owner_id)
    state = parse_qs(urlparse(auth_url).query)["state"][0]

    with pytest.raises(GmailServiceError):
        gmail_service.validate_oauth_state(signed_state, "")
    with pytest.raises(GmailServiceError):
        gmail_service.validate_oauth_state(signed_state, "invalid-state")
    with pytest.raises(GmailServiceError):
        gmail_service.validate_oauth_state(signed_state, state, str(uuid.uuid4()))
    assert gmail_service.validate_oauth_state(signed_state, state)["owner_id"] == owner_id


def test_gmail_oauth_requires_credentials_and_encryption_key(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "")
    monkeypatch.setattr(settings, "GMAIL_ENCRYPTION_KEY", "")
    with pytest.raises(GmailServiceError, match="OAuth is not configured"):
        gmail_service.build_authorization_request(str(uuid.uuid4()))
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "client-secret")
    with pytest.raises(GmailServiceError, match="encryption is not configured"):
        gmail_service.build_authorization_request(str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_oauth_code_exchange_uses_pkce_and_read_only_scope(monkeypatch, gmail_settings):
    calls = []

    async def fake_send_http(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _json_response(
            url,
            {
                "access_token": "provider-access-token",
                "refresh_token": "provider-refresh-token",
                "scope": "openid email https://www.googleapis.com/auth/gmail.readonly",
                "expires_in": 3600,
            },
        )

    monkeypatch.setattr(GmailService, "_send_http", staticmethod(fake_send_http))
    tokens = await gmail_service.exchange_code("authorization-code", "pkce-verifier")

    assert tokens["access_token"] == "provider-access-token"
    assert calls[0][2]["data"]["code_verifier"] == "pkce-verifier"
    assert calls[0][2]["data"]["client_secret"] == settings.GOOGLE_CLIENT_SECRET


def test_oauth_callback_is_bound_to_signed_owner_state(client, monkeypatch, gmail_settings):
    owner_id, access_token = _register_and_login(client)
    auth_url, signed_state = gmail_service.build_authorization_request(owner_id)
    state = parse_qs(urlparse(auth_url).query)["state"][0]
    completed = []

    async def fake_complete_oauth(db, user, code, verifier):
        completed.append((user.id, code, verifier))

    monkeypatch.setattr(gmail_service, "complete_oauth", fake_complete_oauth)
    client.cookies.set(
        gmail_service.oauth_cookie_name(),
        signed_state,
        path=gmail_service.oauth_cookie_path(),
    )
    callback = client.get(
        "/api/v1/communication/gmail/callback",
        params={"state": state, "code": "auth-code"},
        follow_redirects=False,
    )

    assert callback.status_code == 302
    assert "gmail=connected" in callback.headers["location"]
    assert completed and completed[0][0] == owner_id
    assert "provider-access-token" not in callback.text
    assert access_token


def test_gmail_callback_rejects_missing_state(client, gmail_settings):
    response = client.get(
        "/api/v1/communication/gmail/callback",
        params={"code": "auth-code"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "gmail=error" in response.headers["location"]


@pytest.mark.asyncio
async def test_access_token_refresh_encrypts_new_token_and_handles_revocation(
    monkeypatch,
    gmail_settings,
):
    owner_id = _insert_user()
    with SessionLocal() as db:
        connection = gmail_service.save_connection(
            db,
            db.query(User).filter(User.id == owner_id).one(),
            email_address="owner@gmail.com",
            access_token="expired-access",
            refresh_token="working-refresh",
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            expires_in=0,
        )
        calls = []

        async def successful_refresh(method, url, **kwargs):
            calls.append(kwargs["data"])
            return _json_response(
                url,
                {"access_token": "new-access", "expires_in": 3600},
            )

        monkeypatch.setattr(
            GmailService,
            "_send_http",
            staticmethod(successful_refresh),
        )
        assert await gmail_service._refresh_access_token(db, owner_id) == "new-access"
        assert gmail_service.get_access_token(db, owner_id) == "new-access"
        assert calls[0]["grant_type"] == "refresh_token"
        assert connection.connection_status == "connected"

        connection.expires_at = connection.expires_at.replace(year=2000)
        db.commit()

        async def revoked_refresh(method, url, **kwargs):
            return _json_response(url, {"error": "invalid_grant"}, status_code=400)

        monkeypatch.setattr(GmailService, "_send_http", staticmethod(revoked_refresh))
        with pytest.raises(GmailServiceError, match="revoked"):
            await gmail_service._refresh_access_token(db, owner_id, force=True)
        assert connection.connection_status == "reauthorization_required"


def test_reconnecting_different_gmail_account_does_not_keep_stale_refresh_token(
    gmail_settings,
):
    owner_id = _insert_user()
    with SessionLocal() as db:
        user = db.query(User).filter(User.id == owner_id).one()
        connection = gmail_service.save_connection(
            db,
            user,
            email_address="first@gmail.com",
            access_token="first-access",
            refresh_token="first-refresh",
            expires_in=3600,
        )

        updated = gmail_service.save_connection(
            db,
            user,
            email_address="second@gmail.com",
            access_token="second-access",
            expires_in=3600,
        )

        assert updated.id == connection.id
        assert gmail_service.get_access_token(db, owner_id) == "second-access"
        assert gmail_service.get_refresh_token(db, owner_id) is None


@pytest.mark.asyncio
async def test_gmail_listing_unread_search_and_pagination(monkeypatch, gmail_settings):
    owner_id = _insert_user()
    request_params = []
    encoded_body = "SGVsbG8gZnJvbSBHbWFpbA"

    async def fake_google(cls, db, current_owner_id, method, path, *, params=None):
        assert current_owner_id == owner_id
        if path == "messages":
            request_params.append(params or {})
            return _json_response(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                {
                    "messages": [{"id": "message-1", "threadId": "thread-1"}],
                    "nextPageToken": "next-page",
                    "resultSizeEstimate": 5,
                },
            ).json()
        return _json_response(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/message-1",
            {
                "id": "message-1",
                "threadId": "thread-1",
                "labelIds": ["INBOX", "UNREAD"],
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "From", "value": "Rahul <rahul@example.com>"},
                        {"name": "To", "value": "owner@example.com"},
                        {"name": "Subject", "value": "Project update"},
                        {"name": "Date", "value": "Mon, 16 Nov 2026 10:00:00 +0000"},
                    ],
                    "body": {"data": encoded_body},
                },
            },
        ).json()

    monkeypatch.setattr(GmailService, "_google_api_request", classmethod(fake_google))
    with SessionLocal() as db:
        user = db.query(User).filter(User.id == owner_id).one()
        gmail_service.save_connection(
            db,
            user,
            email_address="owner@gmail.com",
            access_token="access",
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            expires_in=3600,
        )
        inbox = await gmail_service.list_messages(
            db,
            owner_id,
            page_token="page-1",
            max_results=1,
        )
        unread = await gmail_service.list_messages(db, owner_id, unread_only=True)
        searched = await gmail_service.list_messages(
            db,
            owner_id,
            query="from:rahul",
        )

    assert inbox["next_page_token"] == "next-page"
    assert inbox["messages"][0]["body"] == "Hello from Gmail"
    assert inbox["messages"][0]["sender"] == "Rahul <rahul@example.com>"
    summarized = gmail_service.add_extractive_summary(inbox)
    assert summarized["summary"] == "Hello from Gmail"
    assert summarized["summary_message_id"] == "message-1"
    assert request_params[0]["pageToken"] == "page-1"
    assert request_params[1]["labelIds"] == ["INBOX", "UNREAD"]
    assert request_params[2]["q"] == "from:rahul"
    assert searched["messages"][0]["thread_id"] == "thread-1"


@pytest.mark.asyncio
async def test_gmail_thread_retrieval_and_malformed_mime(monkeypatch, gmail_settings):
    owner_id = _insert_user()

    async def fake_google(cls, db, current_owner_id, method, path, *, params=None):
        assert current_owner_id == owner_id
        assert path == "threads/thread-1"
        return {
            "id": "thread-1",
            "historyId": "history-1",
            "messages": [
                {
                    "id": "message-1",
                    "threadId": "thread-1",
                    "payload": {
                        "mimeType": "text/html",
                        "body": {
                            "data": "PGRpdj5IZWxsbyA8c2NyaXB0PmFsZXJ0KDEpPC9zY3JpcHQ+PC9kaXY+"
                        },
                    },
                },
                {
                    "id": "message-2",
                    "threadId": "thread-1",
                    "payload": {
                        "mimeType": "text/plain",
                        "body": {"data": "%%%malformed%%%"},
                    },
                },
            ],
        }

    monkeypatch.setattr(GmailService, "_google_api_request", classmethod(fake_google))
    with SessionLocal() as db:
        gmail_service.save_connection(
            db,
            db.query(User).filter(User.id == owner_id).one(),
            email_address="owner@gmail.com",
            access_token="access",
            expires_in=3600,
        )
        thread = await gmail_service.get_thread(db, owner_id, "thread-1")

    assert thread["history_id"] == "history-1"
    assert thread["messages"][0]["body"] == "Hello"
    assert "alert" not in thread["messages"][0]["body"]
    assert thread["messages"][1]["body"] == ""


def test_gmail_connection_is_owner_isolated_and_endpoints_require_auth(
    client,
    gmail_settings,
):
    owner_id, _ = _register_and_login(client)
    response = client.get("/api/v1/communication/gmail/messages")
    assert response.status_code == 401

    other_owner_id = _insert_user()
    with SessionLocal() as db:
        with pytest.raises(GmailServiceError, match="does not belong"):
            gmail_service.ensure_owner_connection(
                db,
                other_owner_id,
                user_id=owner_id,
            )
        assert (
            db.query(GmailConnection)
            .filter(GmailConnection.owner_id == owner_id)
            .count()
            == 0
        )


def test_gmail_read_tool_requires_authenticated_owner_context():
    from app.tools.communication_tools import GmailReadTool

    result = asyncio.run(GmailReadTool().execute({"operation": "inbox"}))
    assert result.success is False
    assert "authenticated owner" in result.error


def test_send_email_is_disabled_and_not_registered():
    from app.agents.communication import communication_agent
    from app.tools import tool_registry
    from app.tools.communication_tools import SendEmailTool

    assert tool_registry.get_tool("send_email") is None
    assert "send_email" not in communication_agent.allowed_tools
    result = asyncio.run(
        SendEmailTool().execute(
            {
                "to_email": "recipient@example.com",
                "subject": "Test",
                "body": "This must not send.",
            },
            context={"db": object(), "user": object()},
        )
    )
    assert result.success is False
    assert result.error == (
        "Email sending is disabled in this phase; only read-only Gmail access is available."
    )


@pytest.mark.asyncio
async def test_existing_orchestrator_routes_email_reads_without_drafting(monkeypatch):
    from app.agents.orchestrator import orchestrator_agent
    from app.services.llm_service import llm_service

    async def unexpected_llm_call(**kwargs):
        raise AssertionError("Email retrieval requests must not be sent to the LLM planner.")

    monkeypatch.setattr(llm_service, "generate_structured", unexpected_llm_call)

    plan = await orchestrator_agent.create_plan("Show my unread emails")
    assert plan.steps[0].tool_id == "gmail_read"
    assert plan.steps[0].input_params["operation"] == "unread"

    ordinary_question = orchestrator_agent._generate_deterministic_plan(
        "How do I write a professional email?"
    )
    assert all(step.tool_id != "gmail_read" for step in ordinary_question.steps)

    summary_plan = await orchestrator_agent.create_plan("Summarize my latest email")
    assert summary_plan.steps[0].tool_id == "gmail_read"
    assert summary_plan.steps[0].input_params["summarize"] is True

    sender_plan = await orchestrator_agent.create_plan(
        "What did Rahul say about tomorrow's meeting?"
    )
    assert sender_plan.steps[0].input_params["operation"] == "search"
    assert sender_plan.steps[0].input_params["query"] == "from:Rahul"

    today_plan = await orchestrator_agent.create_plan(
        "What emails did I receive today?"
    )
    assert today_plan.steps[0].input_params["operation"] == "search"
    assert today_plan.steps[0].input_params["query"].startswith("after:")


def test_gmail_read_endpoint_reports_disconnected_account(client, gmail_settings):
    owner_id, access_token = _register_and_login(client)
    response = client.get(
        "/api/v1/communication/gmail/messages",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 503
    assert "not connected" in response.json()["detail"]
    assert owner_id
