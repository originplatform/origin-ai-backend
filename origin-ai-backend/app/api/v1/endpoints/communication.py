"""Owner-scoped communication and Gmail endpoints."""

from typing import List, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_current_user
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import User
from app.db.models.contact import Contact
from app.db.session import get_db
from app.repositories.contact_repository import contact_repository
from app.repositories.user_repository import user_repository
from app.schemas.communication import (
    ContactCreateRequest,
    ContactResponse,
    ContactUpdateRequest,
    DraftEmailRequest,
    GmailConnectionStatusResponse,
    GmailMessagePage,
    GmailMessageSummary,
    GmailThreadResponse,
)
from app.services.gmail_service import GmailServiceError, gmail_service

router = APIRouter(prefix="/communication")
logger = get_logger("origin.api.communication")

_GMAIL_STATE_MAX_AGE = 600


def _frontend_gmail_redirect(result: str) -> RedirectResponse:
    return RedirectResponse(
        f"{settings.FRONTEND_URL.rstrip('/')}/settings?{urlencode({'gmail': result})}",
        status_code=status.HTTP_302_FOUND,
    )


def _clear_gmail_state_cookie(response: Response) -> None:
    response.delete_cookie(
        gmail_service.oauth_cookie_name(),
        path=gmail_service.oauth_cookie_path(),
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite=settings.COOKIE_SAMESITE,
    )


@router.get("/gmail/connect/start", summary="Start Gmail authorization")
def start_gmail_connection(user: User = Depends(get_current_user)):
    try:
        authorization_url, signed_state = gmail_service.build_authorization_request(user.id)
    except GmailServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    response = RedirectResponse(authorization_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=gmail_service.oauth_cookie_name(),
        value=signed_state,
        max_age=_GMAIL_STATE_MAX_AGE,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        path=gmail_service.oauth_cookie_path(),
    )
    return response


@router.get("/gmail/callback", include_in_schema=False)
async def gmail_oauth_callback(
    request: Request,
    state: Optional[str] = Query(default=None),
    code: Optional[str] = Query(default=None),
    provider_error: Optional[str] = Query(default=None, alias="error"),
    db: Session = Depends(get_db),
):
    signed_state = request.cookies.get(gmail_service.oauth_cookie_name())
    try:
        if not signed_state or not state:
            raise GmailServiceError("Gmail authorization was not completed.")
        state_data = gmail_service.validate_oauth_state(signed_state, state)
        if provider_error or not code:
            raise GmailServiceError("Gmail authorization was not completed.")
        user = user_repository.get_by_id(db, state_data["owner_id"])
        if user is None or not user.is_active:
            raise GmailServiceError("The Gmail connection owner is no longer active.")
        await gmail_service.complete_oauth(
            db,
            user,
            code,
            state_data["verifier"],
        )
        response = _frontend_gmail_redirect("connected")
    except GmailServiceError:
        db.rollback()
        logger.warning("Gmail OAuth callback was not completed.")
        response = _frontend_gmail_redirect("error")
    except Exception:
        db.rollback()
        logger.exception("Unexpected Gmail OAuth callback failure.")
        response = _frontend_gmail_redirect("error")
    _clear_gmail_state_cookie(response)
    return response


@router.get("/gmail/status", response_model=GmailConnectionStatusResponse, summary="Check Gmail connection status")
def get_gmail_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payload = gmail_service.get_status_payload(db, user.id)
    return GmailConnectionStatusResponse(**payload)


@router.get("/gmail/profile", summary="Get the connected Gmail profile")
async def get_gmail_profile(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        profile = await gmail_service.get_profile(db, user.id)
        return {
            "email_address": str(profile.get("emailAddress") or ""),
            "messages_total": int(profile.get("messagesTotal") or 0),
            "threads_total": int(profile.get("threadsTotal") or 0),
        }
    except GmailServiceError as exc:
        raise _gmail_error(exc) from exc


@router.post("/gmail/disconnect", summary="Disconnect Gmail for the authenticated owner")
async def disconnect_gmail(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    revocation_confirmed = await gmail_service.disconnect(db, user.id)
    return {
        "status": "disconnected",
        "provider_revocation": "confirmed" if revocation_confirmed else "not_confirmed",
    }


def _gmail_error(exc: GmailServiceError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=str(exc),
    )


@router.get("/gmail/messages", response_model=GmailMessagePage, summary="Read recent inbox messages")
async def get_gmail_messages(
    page_token: Optional[str] = Query(default=None),
    max_results: int = Query(default=20, ge=1, le=100),
    summarize: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = await gmail_service.list_messages(
            db,
            user.id,
            page_token=page_token,
            max_results=max_results,
        )
        if summarize:
            result = gmail_service.add_extractive_summary(result)
        return GmailMessagePage(**result)
    except GmailServiceError as exc:
        raise _gmail_error(exc) from exc


@router.get("/gmail/messages/unread", response_model=GmailMessagePage, summary="Read unread inbox messages")
async def get_unread_gmail_messages(
    page_token: Optional[str] = Query(default=None),
    max_results: int = Query(default=20, ge=1, le=100),
    summarize: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = await gmail_service.list_messages(
            db,
            user.id,
            unread_only=True,
            page_token=page_token,
            max_results=max_results,
        )
        if summarize:
            result = gmail_service.add_extractive_summary(result)
        return GmailMessagePage(**result)
    except GmailServiceError as exc:
        raise _gmail_error(exc) from exc


@router.get("/gmail/messages/search", response_model=GmailMessagePage, summary="Search Gmail messages")
async def search_gmail_messages(
    q: str = Query(min_length=1, max_length=500),
    page_token: Optional[str] = Query(default=None),
    max_results: int = Query(default=20, ge=1, le=100),
    summarize: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = await gmail_service.list_messages(
            db,
            user.id,
            query=q,
            page_token=page_token,
            max_results=max_results,
        )
        if summarize:
            result = gmail_service.add_extractive_summary(result)
        return GmailMessagePage(**result)
    except GmailServiceError as exc:
        raise _gmail_error(exc) from exc


@router.get("/gmail/messages/{message_id}", response_model=GmailMessageSummary, summary="Read a Gmail message")
async def get_gmail_message(
    message_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return await gmail_service.get_message(db, user.id, message_id)
    except GmailServiceError as exc:
        raise _gmail_error(exc) from exc


@router.get("/gmail/threads/{thread_id}", response_model=GmailThreadResponse, summary="Read a Gmail thread")
async def get_gmail_thread(
    thread_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return await gmail_service.get_thread(db, user.id, thread_id)
    except GmailServiceError as exc:
        raise _gmail_error(exc) from exc


@router.get("/contacts", response_model=List[ContactResponse], summary="List owner-scoped contacts")
def list_contacts(
    q: Optional[str] = Query(default=None, description="Optional search text for contact lookup"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if q:
        contacts = contact_repository.search(db, user.id, q)
    else:
        contacts = contact_repository.list_for_owner(db, user.id)
    return contacts


@router.post("/contacts", response_model=ContactResponse, status_code=status.HTTP_201_CREATED, summary="Create an owner-scoped contact")
def create_contact(
    payload: ContactCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = contact_repository.resolve(db, user.id, payload.email_address)
    if existing is not None and existing.email_address.casefold() == payload.email_address.casefold():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Contact already exists for this owner.")
    contact = Contact(
        owner_id=user.id,
        full_name=payload.full_name.strip(),
        email_address=payload.email_address.strip().casefold(),
        aliases=list(payload.aliases or []),
        organization=payload.organization.strip() if payload.organization else None,
        verification_status=payload.verification_status,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


@router.get("/contacts/{contact_id}", response_model=ContactResponse, summary="Get one owner-scoped contact")
def get_contact(
    contact_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    contact = contact_repository.get_by_id(db, user.id, contact_id)
    if not contact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found.")
    return contact


@router.patch("/contacts/{contact_id}", response_model=ContactResponse, summary="Update an owner-scoped contact")
def update_contact(
    contact_id: str,
    payload: ContactUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    contact = contact_repository.get_by_id(db, user.id, contact_id)
    if not contact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found.")
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        if value is not None:
            setattr(contact, field, value)
    if getattr(contact, "email_address", None):
        contact.email_address = str(contact.email_address).strip().casefold()
    db.commit()
    db.refresh(contact)
    return contact


@router.delete("/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an owner-scoped contact")
def delete_contact(
    contact_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    contact = contact_repository.get_by_id(db, user.id, contact_id)
    if not contact:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found.")
    db.delete(contact)
    db.commit()


@router.post("/drafts", response_model=dict, summary="Prepare an authenticated email draft")
def prepare_draft(
    payload: DraftEmailRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not gmail_service.is_connected(db, user.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Gmail is not connected for this account. Connect Gmail before sending or drafting from provider-backed mail actions.",
        )
    return {
        "status": "draft_ready",
        "owner_id": user.id,
        "to_email": str(payload.to_email).strip().casefold(),
        "subject": payload.subject,
        "body": payload.body,
        "attachments": list(payload.attachments or []),
    }


__all__ = ["router"]
