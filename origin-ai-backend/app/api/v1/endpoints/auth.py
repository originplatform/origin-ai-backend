"""Authentication API routes."""

from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.v1.dependencies import get_current_user
from app.core.auth_security import csrf_token_matches
from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import (
    AuthResponse,
    CsrfTokenResponse,
    LoginRequest,
    RegisterRequest,
    UserResponse,
)
from app.services.auth_service import (
    DuplicateUserError,
    auth_service,
)
from app.services.google_oauth_service import (
    GoogleAccountConflict,
    GoogleOAuthError,
    GoogleOAuthNotConfigured,
    google_oauth_service,
)
from app.services.token_service import InvalidRefreshToken, token_service


router = APIRouter(prefix="/auth")

_REFRESH_COOKIE = "origin_refresh"
_CSRF_COOKIE = "origin_csrf"
_REFRESH_COOKIE_PATH = "/api/v1/auth"
_CSRF_HEADER = "X-CSRF-Token"


def _error(
    status_code: int,
    code: str,
    message: str,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _set_session_cookies(response: Response, tokens) -> None:
    max_age = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    cookie_settings = {
        "max_age": max_age,
        "secure": settings.COOKIE_SECURE,
        "samesite": settings.COOKIE_SAMESITE,
        "path": _REFRESH_COOKIE_PATH,
    }
    response.set_cookie(
        _REFRESH_COOKIE,
        tokens.refresh_token,
        httponly=True,
        **cookie_settings,
    )
    response.set_cookie(
        _CSRF_COOKIE,
        tokens.csrf_token,
        httponly=True,
        **cookie_settings,
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(
        _REFRESH_COOKIE,
        path=_REFRESH_COOKIE_PATH,
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite=settings.COOKIE_SAMESITE,
    )
    response.delete_cookie(
        _CSRF_COOKIE,
        path=_REFRESH_COOKIE_PATH,
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite=settings.COOKIE_SAMESITE,
    )


def _auth_response(tokens) -> AuthResponse:
    return AuthResponse(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        csrf_token=tokens.csrf_token,
        user=UserResponse.model_validate(tokens.user),
    )


def _frontend_redirect(result: str) -> RedirectResponse:
    parts = urlsplit(settings.FRONTEND_URL)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.append(("auth", result))
    target = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


def _set_oauth_state_cookie(response: Response, signed_state: str) -> None:
    response.set_cookie(
        google_oauth_service.oauth_state_cookie_name,
        signed_state,
        max_age=600,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path=google_oauth_service.oauth_state_cookie_path,
    )


def _clear_oauth_state_cookie(response: Response) -> None:
    response.delete_cookie(
        google_oauth_service.oauth_state_cookie_name,
        path=google_oauth_service.oauth_state_cookie_path,
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register an account",
)
@limiter.limit(settings.AUTH_REGISTER_RATE_LIMIT)
def register(
    request: Request,
    response: Response,
    payload: RegisterRequest,
    db: Session = Depends(get_db),
):
    try:
        return auth_service.register(db, payload)
    except DuplicateUserError:
        raise _error(
            status.HTTP_409_CONFLICT,
            "account_exists",
            "An account with this email already exists.",
        )


@router.post(
    "/login",
    response_model=AuthResponse,
    summary="Log in with email and password",
)
@limiter.limit(settings.AUTH_LOGIN_RATE_LIMIT)
def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    db: Session = Depends(get_db),
):
    user = auth_service.authenticate(db, str(payload.email), payload.password)
    if user is None:
        raise _error(
            status.HTTP_401_UNAUTHORIZED,
            "invalid_credentials",
            "Email or password is incorrect.",
        )
    tokens = token_service.issue_session(
        db,
        user,
        request.headers.get("user-agent"),
    )
    _set_session_cookies(response, tokens)
    return _auth_response(tokens)


@router.post(
    "/refresh",
    response_model=AuthResponse,
    summary="Rotate the refresh-token session",
)
def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    raw_token = request.cookies.get(_REFRESH_COOKIE)
    if not raw_token:
        raise _error(
            status.HTTP_401_UNAUTHORIZED,
            "invalid_refresh_token",
            "Refresh session is unavailable.",
        )
    if not csrf_token_matches(
        request.cookies.get(_CSRF_COOKIE),
        request.headers.get(_CSRF_HEADER),
    ):
        raise _error(
            status.HTTP_403_FORBIDDEN,
            "csrf_validation_failed",
            "CSRF validation failed.",
        )
    try:
        tokens = token_service.rotate(db, raw_token)
    except InvalidRefreshToken:
        raise _error(
            status.HTTP_401_UNAUTHORIZED,
            "invalid_refresh_token",
            "Refresh session is invalid or expired.",
        )
    _set_session_cookies(response, tokens)
    return _auth_response(tokens)


@router.get(
    "/csrf",
    response_model=CsrfTokenResponse,
    summary="Get the CSRF token for cookie-authenticated requests",
)
def get_csrf_token(request: Request):
    csrf_token = request.cookies.get(_CSRF_COOKIE)
    if not csrf_token:
        raise _error(
            status.HTTP_401_UNAUTHORIZED,
            "csrf_token_unavailable",
            "No active refresh session is available.",
        )
    return CsrfTokenResponse(csrf_token=csrf_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Log out")
def logout(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    raw_token = request.cookies.get(_REFRESH_COOKIE)
    if raw_token and not csrf_token_matches(
        request.cookies.get(_CSRF_COOKIE),
        request.headers.get(_CSRF_HEADER),
    ):
        raise _error(
            status.HTTP_403_FORBIDDEN,
            "csrf_validation_failed",
            "CSRF validation failed.",
        )
    if raw_token:
        token_service.revoke_session(db, raw_token, user.id)
    _clear_session_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post(
    "/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Log out all sessions",
)
def logout_all(
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    token_service.revoke_all_sessions(db, user.id)
    _clear_session_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserResponse, summary="Get the current user")
def current_user(user: User = Depends(get_current_user)):
    return user


def _begin_google_auth(link_user_id: Optional[str] = None) -> RedirectResponse:
    try:
        authorization_url, signed_state = (
            google_oauth_service.build_authorization_request(
                link_user_id=link_user_id,
            )
        )
    except GoogleOAuthNotConfigured:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "google_oauth_unavailable",
            "Google sign-in is not configured.",
        )
    redirect_response = RedirectResponse(
        authorization_url,
        status_code=status.HTTP_302_FOUND,
    )
    _set_oauth_state_cookie(redirect_response, signed_state)
    return redirect_response


@router.get("/google", summary="Start Google Sign-In")
@limiter.limit("10/minute")
def google_login(request: Request):
    return _begin_google_auth()


@router.get("/google/link", summary="Link a Google identity to the current account")
@limiter.limit("10/minute")
def google_link(
    request: Request,
    user: User = Depends(get_current_user),
):
    return _begin_google_auth(user.id)


@router.get("/google/callback", summary="Complete Google Sign-In")
@limiter.limit("10/minute")
async def google_callback(
    request: Request,
    state: Optional[str] = Query(default=None),
    code: Optional[str] = Query(default=None),
    provider_error: Optional[str] = Query(default=None, alias="error"),
    db: Session = Depends(get_db),
):
    signed_state = request.cookies.get(google_oauth_service.oauth_state_cookie_name)
    try:
        if not signed_state or not state:
            raise GoogleOAuthError
        state_data = google_oauth_service.validate_state(signed_state, state)
        if provider_error:
            raise GoogleOAuthError
        if not code:
            raise GoogleOAuthError
        encoded_id_token = await google_oauth_service.exchange_code(
            code,
            state_data["verifier"],
        )
        claims = await google_oauth_service.verify_id_token(
            encoded_id_token,
            state_data["nonce"],
        )
        user = google_oauth_service.resolve_user(
            db,
            claims,
            link_user_id=state_data.get("link_user_id"),
        )
        tokens = token_service.issue_session(
            db,
            user,
            request.headers.get("user-agent"),
        )
        redirect_response = _frontend_redirect("success")
        _set_session_cookies(redirect_response, tokens)
        _clear_oauth_state_cookie(redirect_response)
        return redirect_response
    except GoogleAccountConflict:
        redirect_response = _frontend_redirect("account_conflict")
    except GoogleOAuthError:
        redirect_response = _frontend_redirect("google_auth_failed")
    except (SQLAlchemyError, RuntimeError):
        db.rollback()
        redirect_response = _frontend_redirect("google_auth_failed")
    _clear_oauth_state_cookie(redirect_response)
    return redirect_response


__all__ = ["router"]
