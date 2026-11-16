"""Owner-scoped Gmail OAuth, token, and read-only API operations."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.core.auth_security import _signing_key
from app.core.config import settings
from app.db.models import GmailConnection, User


_GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
_GMAIL_API_ROOT = "https://gmail.googleapis.com/gmail/v1/users/me"
_GMAIL_READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
_GMAIL_OAUTH_COOKIE = "origin_gmail_oauth"
_GMAIL_OAUTH_COOKIE_PATH = "/api/v1/communication/gmail/callback"


class GmailServiceError(RuntimeError):
    """Raised when Gmail configuration, credentials, or provider operations fail."""


class _SafeHTMLTextExtractor(HTMLParser):
    """Extract visible text without exposing executable markup to clients."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self._parts: List[str] = []

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, Optional[str]]]) -> None:
        super().handle_starttag(tag, _attrs)
        if tag.casefold() in {"script", "style", "head"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "head"} and self._hidden_depth:
            self._hidden_depth -= 1
        elif tag.casefold() in {"br", "p", "div", "li", "tr"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self._parts.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self._parts).split())


class GmailService:
    """Securely stores the authenticated owner's Gmail connection and reads mail."""

    @staticmethod
    def oauth_cookie_name() -> str:
        return _GMAIL_OAUTH_COOKIE

    @staticmethod
    def oauth_cookie_path() -> str:
        return _GMAIL_OAUTH_COOKIE_PATH

    @staticmethod
    def _require_oauth_configuration() -> None:
        if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
            raise GmailServiceError("Google OAuth is not configured.")
        if not settings.GMAIL_ENCRYPTION_KEY:
            raise GmailServiceError("Gmail token encryption is not configured.")

    @staticmethod
    def _key() -> bytes:
        secret = settings.GMAIL_ENCRYPTION_KEY
        if not secret:
            raise GmailServiceError("Gmail token encryption is not configured.")
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)

    @staticmethod
    def _state_serializer() -> URLSafeTimedSerializer:
        return URLSafeTimedSerializer(
            _signing_key(),
            salt="origin-ai-gmail-oauth-state-v1",
        )

    @classmethod
    def encrypt(cls, value: str) -> str:
        if not value:
            return ""
        try:
            return Fernet(cls._key()).encrypt(value.encode("utf-8")).decode("ascii")
        except (ValueError, TypeError) as exc:
            raise GmailServiceError("Gmail token encryption failed.") from exc

    @classmethod
    def decrypt(cls, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        try:
            return Fernet(cls._key()).decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, UnicodeError) as exc:
            raise GmailServiceError("Stored Gmail credentials cannot be decrypted.") from exc

    @classmethod
    def build_authorization_request(cls, owner_id: str) -> tuple[str, str]:
        cls._require_oauth_configuration()
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).decode("ascii").rstrip("=")
        signed_state = cls._state_serializer().dumps(
            {
                "owner_id": owner_id,
                "state": state,
                "verifier": verifier,
            }
        )
        query = urlencode(
            {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "redirect_uri": settings.GOOGLE_GMAIL_REDIRECT_URI,
                "response_type": "code",
                "scope": f"openid email {_GMAIL_READ_SCOPE}",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
            }
        )
        return f"{_GOOGLE_AUTHORIZATION_ENDPOINT}?{query}", signed_state

    @classmethod
    def validate_oauth_state(
        cls,
        signed_state: str,
        returned_state: str,
        expected_owner_id: Optional[str] = None,
    ) -> Dict[str, str]:
        try:
            data = cls._state_serializer().loads(signed_state, max_age=600)
        except (BadSignature, SignatureExpired) as exc:
            raise GmailServiceError("Gmail authorization state is invalid or expired.") from exc
        owner_id = data.get("owner_id")
        state = data.get("state")
        verifier = data.get("verifier")
        if (
            not isinstance(owner_id, str)
            or not isinstance(state, str)
            or not isinstance(verifier, str)
            or not secrets.compare_digest(state, returned_state)
            or (
                expected_owner_id is not None
                and not secrets.compare_digest(owner_id, expected_owner_id)
            )
        ):
            raise GmailServiceError("Gmail authorization state is invalid.")
        return {"owner_id": owner_id, "verifier": verifier}

    @classmethod
    async def exchange_code(cls, code: str, verifier: str) -> Dict[str, Any]:
        cls._require_oauth_configuration()
        try:
            response = await cls._send_http(
                "POST",
                _GOOGLE_TOKEN_ENDPOINT,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": settings.GOOGLE_GMAIL_REDIRECT_URI,
                    "grant_type": "authorization_code",
                    "code_verifier": verifier,
                },
            )
            response.raise_for_status()
            tokens = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GmailServiceError("Google rejected the Gmail authorization.") from exc
        if not isinstance(tokens, dict) or not isinstance(tokens.get("access_token"), str):
            raise GmailServiceError("Google returned an invalid Gmail authorization response.")
        returned_scopes = set(str(tokens.get("scope") or "").split())
        if _GMAIL_READ_SCOPE not in returned_scopes:
            raise GmailServiceError("Google did not grant the required Gmail read-only scope.")
        return tokens

    @classmethod
    async def complete_oauth(
        cls,
        db: Session,
        user: User,
        code: str,
        verifier: str,
    ) -> GmailConnection:
        tokens = await cls.exchange_code(code, verifier)
        try:
            response = await cls._send_http(
                "GET",
                f"{_GMAIL_API_ROOT}/profile",
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
            )
            response.raise_for_status()
            profile = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GmailServiceError("Gmail profile verification failed.") from exc
        email_address = profile.get("emailAddress") if isinstance(profile, dict) else None
        if not isinstance(email_address, str) or "@" not in email_address:
            raise GmailServiceError("Google returned an invalid Gmail profile.")
        return cls.save_connection(
            db,
            user,
            email_address=email_address,
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token"),
            scopes=str(tokens.get("scope") or "").split(),
            expires_in=int(tokens.get("expires_in", 3600)),
        )

    @staticmethod
    async def _send_http(method: str, url: str, **kwargs: Any) -> httpx.Response:
        async with httpx.AsyncClient(timeout=15.0) as client:
            return await client.request(method, url, **kwargs)

    @classmethod
    def get_connection(cls, db: Session, owner_id: str) -> Optional[GmailConnection]:
        return (
            db.query(GmailConnection)
            .filter(GmailConnection.owner_id == owner_id)
            .first()
        )

    @classmethod
    def is_connected(cls, db: Session, owner_id: str) -> bool:
        connection = cls.get_connection(db, owner_id)
        return bool(connection and connection.connection_status == "connected")

    @classmethod
    def save_connection(
        cls,
        db: Session,
        user: User,
        *,
        email_address: str,
        access_token: str,
        refresh_token: Optional[str] = None,
        google_sub: Optional[str] = None,
        scopes: Optional[list[str]] = None,
        expires_in: Optional[int] = None,
    ) -> GmailConnection:
        cls._key()
        connection = cls.get_connection(db, user.id)
        normalized_email = email_address.strip().casefold()
        if connection is None:
            connection = GmailConnection(owner_id=user.id)
            db.add(connection)
        elif (
            connection.email_address.casefold() != normalized_email
            and not refresh_token
        ):
            connection.refresh_token_encrypted = None
        connection.email_address = normalized_email
        connection.google_sub = google_sub
        connection.access_token_encrypted = cls.encrypt(access_token)
        if refresh_token:
            connection.refresh_token_encrypted = cls.encrypt(refresh_token)
        connection.token_type = "Bearer"
        connection.scopes = dict.fromkeys(scopes or [], True)
        connection.connection_status = "connected"
        connection.expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=max(0, expires_in))
            if expires_in is not None
            else None
        )
        db.commit()
        db.refresh(connection)
        return connection

    @classmethod
    def get_status_payload(cls, db: Session, owner_id: str) -> Dict[str, Any]:
        connection = cls.get_connection(db, owner_id)
        if connection is None:
            return {
                "connected": False,
                "status": "not_connected",
                "email_address": None,
                "scopes": [],
            }
        return {
            "connected": connection.connection_status == "connected",
            "status": connection.connection_status,
            "email_address": connection.email_address,
            "scopes": list((connection.scopes or {}).keys()),
        }

    @classmethod
    def get_access_token(cls, db: Session, owner_id: str) -> Optional[str]:
        connection = cls.get_connection(db, owner_id)
        if not connection or connection.connection_status != "connected":
            return None
        return cls.decrypt(connection.access_token_encrypted)

    @classmethod
    def get_refresh_token(cls, db: Session, owner_id: str) -> Optional[str]:
        connection = cls.get_connection(db, owner_id)
        if not connection or connection.connection_status != "connected":
            return None
        return cls.decrypt(connection.refresh_token_encrypted)

    @classmethod
    def ensure_owner_connection(
        cls,
        db: Session,
        owner_id: str,
        *,
        user_id: str,
    ) -> GmailConnection:
        if not secrets.compare_digest(owner_id, user_id):
            raise GmailServiceError("This Gmail account does not belong to the authenticated owner.")
        connection = cls.get_connection(db, owner_id)
        if connection is None or connection.connection_status != "connected":
            raise GmailServiceError("Gmail is not connected for this account.")
        return connection

    @classmethod
    def _set_reauthorization_required(cls, db: Session, connection: GmailConnection) -> None:
        connection.connection_status = "reauthorization_required"
        db.commit()

    @classmethod
    async def _refresh_access_token(
        cls,
        db: Session,
        owner_id: str,
        *,
        force: bool = False,
    ) -> str:
        connection = cls.ensure_owner_connection(db, owner_id, user_id=owner_id)
        now = datetime.now(timezone.utc)
        expires_at = connection.expires_at
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if (
            not force
            and connection.access_token_encrypted
            and (expires_at is None or expires_at > now + timedelta(seconds=60))
        ):
            token = cls.decrypt(connection.access_token_encrypted)
            if token:
                return token

        refresh_token = cls.decrypt(connection.refresh_token_encrypted)
        if not refresh_token:
            cls._set_reauthorization_required(db, connection)
            raise GmailServiceError("Gmail authorization expired. Reconnect Gmail to continue.")
        try:
            cls._require_oauth_configuration()
            response = await cls._send_http(
                "POST",
                _GOOGLE_TOKEN_ENDPOINT,
                data={
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            response.raise_for_status()
            tokens = response.json()
        except (httpx.HTTPError, ValueError, GmailServiceError) as exc:
            cls._set_reauthorization_required(db, connection)
            raise GmailServiceError("Gmail authorization expired or was revoked. Reconnect Gmail.") from exc
        if not isinstance(tokens, dict):
            cls._set_reauthorization_required(db, connection)
            raise GmailServiceError("Google returned invalid refreshed credentials.")
        access_token = tokens.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            cls._set_reauthorization_required(db, connection)
            raise GmailServiceError("Google returned invalid refreshed credentials.")

        connection.access_token_encrypted = cls.encrypt(access_token)
        if isinstance(tokens.get("refresh_token"), str) and tokens["refresh_token"]:
            connection.refresh_token_encrypted = cls.encrypt(tokens["refresh_token"])
        try:
            expires_in = max(0, int(tokens.get("expires_in", 3600)))
        except (TypeError, ValueError):
            expires_in = 3600
        connection.expires_at = now + timedelta(seconds=expires_in)
        connection.connection_status = "connected"
        db.commit()
        return access_token

    @classmethod
    async def _google_api_request(
        cls,
        db: Session,
        owner_id: str,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        connection = cls.ensure_owner_connection(db, owner_id, user_id=owner_id)
        token = await cls._refresh_access_token(db, owner_id)
        url = f"{_GMAIL_API_ROOT}/{path.lstrip('/')}"
        try:
            response = await cls._send_http(
                method,
                url,
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
            if response.status_code == 401:
                token = await cls._refresh_access_token(db, owner_id, force=True)
                response = await cls._send_http(
                    method,
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    params=params,
                )
            if response.status_code == 401:
                cls._set_reauthorization_required(db, connection)
                raise GmailServiceError("Gmail authorization is no longer valid. Reconnect Gmail.")
            response.raise_for_status()
            result = response.json()
        except GmailServiceError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise GmailServiceError("Gmail could not complete the read request.") from exc
        if not isinstance(result, dict):
            raise GmailServiceError("Gmail returned an invalid response.")
        return result

    @classmethod
    async def get_profile(cls, db: Session, owner_id: str) -> Dict[str, Any]:
        return await cls._google_api_request(db, owner_id, "GET", "profile")

    @staticmethod
    def _decode_header(value: Optional[str]) -> str:
        if not value:
            return ""
        try:
            return str(make_header(decode_header(value)))
        except (LookupError, UnicodeError, ValueError):
            return value

    @staticmethod
    def _decode_body(data: Optional[str], mime_type: str, charset: Optional[str]) -> str:
        if not data:
            return ""
        try:
            raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
        except (binascii.Error, ValueError):
            return ""
        encoding = charset or "utf-8"
        try:
            decoded = raw.decode(encoding, errors="replace")
        except LookupError:
            decoded = raw.decode("utf-8", errors="replace")
        if mime_type.casefold() == "text/html":
            extractor = _SafeHTMLTextExtractor()
            try:
                extractor.feed(decoded)
                extractor.close()
                return extractor.text()
            except ValueError:
                return ""
        return decoded

    @classmethod
    def _extract_body(cls, payload: Dict[str, Any]) -> str:
        plain_parts: List[str] = []
        html_parts: List[str] = []

        def visit(part: Dict[str, Any]) -> None:
            body = part.get("body") or {}
            mime_type = str(part.get("mimeType") or "")
            data = body.get("data") if isinstance(body, dict) else None
            if data and mime_type.casefold() in {"text/plain", "text/html"}:
                charset = None
                part_headers = part.get("headers")
                if isinstance(part_headers, list):
                    for header in part_headers:
                        if (
                            isinstance(header, dict)
                            and str(header.get("name") or "").casefold() == "content-type"
                        ):
                            content_type = str(header.get("value") or "")
                            for parameter in content_type.split(";")[1:]:
                                key, separator, value = parameter.strip().partition("=")
                                if separator and key.casefold() == "charset":
                                    charset = value.strip().strip("\"'")
                decoded = cls._decode_body(str(data), mime_type, charset)
                if mime_type.casefold() == "text/plain":
                    plain_parts.append(decoded)
                else:
                    html_parts.append(decoded)
            children = part.get("parts")
            if isinstance(children, list):
                for child in children:
                    if isinstance(child, dict):
                        visit(child)

        visit(payload)
        return "\n".join(plain_parts or html_parts).strip()

    @classmethod
    def _parse_message(cls, message: Dict[str, Any]) -> Dict[str, Any]:
        payload = message.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        headers = payload.get("headers")
        headers = headers if isinstance(headers, list) else []
        values: Dict[str, str] = {}
        for header in headers:
            if isinstance(header, dict):
                name = str(header.get("name") or "").casefold()
                if name in {"from", "to", "subject", "date"}:
                    values[name] = cls._decode_header(str(header.get("value") or ""))
        thread_id = str(message.get("threadId") or "")
        date_value = values.get("date", "")
        if not date_value and message.get("internalDate"):
            try:
                date_value = datetime.fromtimestamp(
                    int(message["internalDate"]) / 1000,
                    timezone.utc,
                ).isoformat()
            except (TypeError, ValueError, OSError):
                date_value = ""
        else:
            try:
                parsed_date = parsedate_to_datetime(date_value)
                if parsed_date:
                    date_value = parsed_date.isoformat()
            except (TypeError, ValueError, OverflowError):
                pass
        body = cls._extract_body(payload)
        return {
            "id": str(message.get("id") or ""),
            "thread_id": thread_id,
            "sender": values.get("from", ""),
            "recipient": values.get("to", ""),
            "subject": values.get("subject", ""),
            "date": date_value,
            "snippet": str(message.get("snippet") or ""),
            "body": body,
            "labels": [
                str(label)
                for label in (message.get("labelIds") or [])
                if isinstance(label, str)
            ],
        }

    @staticmethod
    def extractive_summary(text: str, *, max_sentences: int = 3) -> str:
        """Return a short extractive summary without sending email content to an LLM."""
        normalized = " ".join(text.split())
        if not normalized:
            return ""
        sentences = re.split(r"(?<=[.!?])\s+", normalized)
        return " ".join(sentences[:max_sentences])[:1000]

    @classmethod
    def add_extractive_summary(cls, result: Dict[str, Any]) -> Dict[str, Any]:
        messages = result.get("messages")
        message = messages[0] if isinstance(messages, list) and messages else result
        if not isinstance(message, dict):
            return result
        result["summary"] = cls.extractive_summary(
            str(message.get("body") or message.get("snippet") or "")
        )
        result["summary_message_id"] = message.get("id")
        return result

    @classmethod
    async def list_messages(
        cls,
        db: Session,
        owner_id: str,
        *,
        unread_only: bool = False,
        query: Optional[str] = None,
        page_token: Optional[str] = None,
        max_results: int = 20,
    ) -> Dict[str, Any]:
        if not 1 <= max_results <= 100:
            raise GmailServiceError("max_results must be between 1 and 100.")
        params: Dict[str, Any] = {"maxResults": max_results}
        if page_token:
            params["pageToken"] = page_token
        label_ids = ["INBOX"]
        if unread_only:
            label_ids.append("UNREAD")
            params["labelIds"] = label_ids
        elif not query:
            params["labelIds"] = label_ids
        if query:
            params["q"] = query
        listing = await cls._google_api_request(db, owner_id, "GET", "messages", params=params)
        messages = listing.get("messages") or []
        if not isinstance(messages, list):
            messages = []
        parsed: List[Dict[str, Any]] = []
        for item in messages:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            result = await cls.get_message(db, owner_id, str(item["id"]))
            parsed.append(result)
        try:
            result_size_estimate = int(listing.get("resultSizeEstimate") or 0)
        except (TypeError, ValueError):
            result_size_estimate = 0
        next_page_token = listing.get("nextPageToken")
        return {
            "messages": parsed,
            "next_page_token": next_page_token if isinstance(next_page_token, str) else None,
            "result_size_estimate": result_size_estimate,
        }

    @classmethod
    async def get_message(cls, db: Session, owner_id: str, message_id: str) -> Dict[str, Any]:
        if not message_id or len(message_id) > 512:
            raise GmailServiceError("A valid Gmail message ID is required.")
        response = await cls._google_api_request(
            db,
            owner_id,
            "GET",
            f"messages/{quote(message_id, safe='')}",
            params={"format": "full"},
        )
        return cls._parse_message(response)

    @classmethod
    async def get_thread(cls, db: Session, owner_id: str, thread_id: str) -> Dict[str, Any]:
        if not thread_id or len(thread_id) > 512:
            raise GmailServiceError("A valid Gmail thread ID is required.")
        response = await cls._google_api_request(
            db,
            owner_id,
            "GET",
            f"threads/{quote(thread_id, safe='')}",
            params={"format": "full"},
        )
        raw_messages = response.get("messages") or []
        parsed = [
            cls._parse_message(message)
            for message in raw_messages
            if isinstance(message, dict)
        ]
        return {
            "id": str(response.get("id") or thread_id),
            "history_id": str(response.get("historyId") or "") or None,
            "messages": parsed,
        }

    @classmethod
    async def disconnect(cls, db: Session, owner_id: str) -> bool:
        connection = cls.get_connection(db, owner_id)
        if not connection:
            return True
        credentials = []
        revocation_confirmed = True
        for encrypted in (
            connection.refresh_token_encrypted,
            connection.access_token_encrypted,
        ):
            try:
                token = cls.decrypt(encrypted)
            except GmailServiceError:
                token = None
                revocation_confirmed = False
            if token:
                credentials.append(token)
        for token in credentials:
            try:
                response = await cls._send_http(
                    "POST",
                    _GOOGLE_REVOKE_ENDPOINT,
                    data={"token": token},
                )
                if response.status_code >= 400:
                    revocation_confirmed = False
            except httpx.HTTPError:
                revocation_confirmed = False
        db.delete(connection)
        db.commit()
        return revocation_confirmed


gmail_service = GmailService()
