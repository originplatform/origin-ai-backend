# Authentication service

The authentication API is mounted under `/api/v1`. It uses the existing SQLAlchemy
engine, model base, and database session. Existing task and agent endpoints do not
require an access token unless they already did.

## Configuration

Copy `.env.example` to `.env` for local development. Set a random
`JWT_SECRET_KEY` (at least 32 bytes for HS256) and configure `DATABASE_URL` as
needed. Without a configured key, development uses a process-local random key;
tokens are invalidated when the process restarts. Production requires a strong
secret, HTTPS frontend and Google callback URLs, HTTPS CORS origins, and
`COOKIE_SECURE=true`.

Configure `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` together to enable Google
Sign-In and Gmail. Set `GOOGLE_REDIRECT_URI` to the Google Sign-In callback and
`GOOGLE_GMAIL_REDIRECT_URI` to the Gmail OAuth callback. Set `GMAIL_ENCRYPTION_KEY`
to a persistent, randomly generated secret of at least 32 bytes; it encrypts Gmail
tokens at rest and must remain stable across restarts. These credentials are never
sent to the frontend or LLM. Gmail OAuth is unavailable if Google credentials or
the encryption key are not configured. Email verification delivery is not implemented.

## Database migrations

Back up the database, then apply the additive migrations from the backend
directory:

```powershell
python -m alembic upgrade head
```

Apply migrations before starting the backend; application startup does not create
or alter database tables.

The chain adds authentication fields to `users` and creates `refresh_tokens`;
it does not recreate existing tables. The migration backfills `full_name` from
the legacy `name` column (or email when name is empty). Do not use downgrade as
an operational rollback after accounts or sessions have been created: downgrading
removes the added authentication fields and refresh-token table.

The communication migrations add owner-scoped contacts and Gmail connections,
then add nullable `expires_at` for access-token refresh. Apply them using
`python -m alembic upgrade head`; existing users and tables are preserved.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/auth/register` | Register with email and password |
| `POST` | `/api/v1/auth/login` | Authenticate and issue access/refresh tokens |
| `POST` | `/api/v1/auth/refresh` | Rotate the refresh-token session |
| `POST` | `/api/v1/auth/logout` | Revoke the current refresh session |
| `POST` | `/api/v1/auth/logout-all` | Revoke all sessions for the authenticated user |
| `GET` | `/api/v1/auth/me` | Return the authenticated user |
| `GET` | `/api/v1/auth/csrf` | Return the CSRF token for a cookie-authenticated request |
| `GET` / `PATCH` | `/api/v1/users/me` | Read or update the authenticated user's profile |
| `GET` | `/api/v1/auth/google` | Start Google Sign-In |
| `GET` | `/api/v1/auth/google/link` | Start explicit Google linking for the current user |
| `GET` | `/api/v1/auth/google/callback` | Handle the Google authorization response |
| `GET` | `/api/v1/communication/gmail/connect/start` | Start authenticated, read-only Gmail OAuth |
| `GET` | `/api/v1/communication/gmail/callback` | Complete the state-bound Gmail OAuth flow |
| `GET` | `/api/v1/communication/gmail/status` | Check the current owner's Gmail connection |
| `POST` | `/api/v1/communication/gmail/disconnect` | Revoke and remove the current owner's Gmail connection |
| `GET` | `/api/v1/communication/gmail/profile` | Read the connected Gmail profile |
| `GET` | `/api/v1/communication/gmail/messages` | Read a paginated recent inbox (`summarize=true` adds a local extractive summary) |
| `GET` | `/api/v1/communication/gmail/messages/unread` | Read a paginated unread inbox |
| `GET` | `/api/v1/communication/gmail/messages/search?q=...` | Search Gmail messages |
| `GET` | `/api/v1/communication/gmail/messages/{message_id}` | Read one Gmail message |
| `GET` | `/api/v1/communication/gmail/threads/{thread_id}` | Read a complete Gmail thread |

Registration requires a password of at least 12 characters. Access tokens are
returned in JSON and should be sent as `Authorization: Bearer <access_token>`.
Refresh tokens are opaque, stored only as hashes in the database, and issued in
HttpOnly cookies.

Refresh and logout are protected against CSRF: send the value returned as
`csrf_token` by login/refresh (or by `GET /api/v1/auth/csrf`) in the
`X-CSRF-Token` header. The CSRF cookie is HttpOnly; the frontend should use the
JSON token rather than reading that cookie. Refresh rotates the cookie and
replay of a previously used refresh token revokes its token family.

Google sign-in uses OIDC state, nonce, and PKCE. The callback redirects to the
frontend with an `auth` result and sets the session cookies on success. After
the redirect, the frontend can call `GET /api/v1/auth/csrf`, then
`POST /api/v1/auth/refresh` with the returned CSRF token to obtain an access
token. An existing account is not linked based on matching email alone; linking
must be started from an authenticated account.

Gmail uses a separate owner-bound OAuth state cookie and PKCE flow. The
`/communication/gmail/connect/start` endpoint requires a bearer access token;
the Google callback validates its short-lived signed cookie and redirects with a
generic connection result. Gmail access is limited to the read-only
`gmail.readonly` scope plus OpenID/email identity scopes. Access and refresh
tokens are encrypted in `gmail_connections`; they are not returned by any API.
Inbox/message/thread reads require authentication and always derive the owner
from the verified JWT. Disconnection removes local credentials even if Google's
revocation endpoint cannot confirm revocation; the response reports that outcome.
Email sending is not registered or available in this phase.
Email summaries are extractive and generated locally; received message content is
not sent to the LLM planner. The task phrase “received today” uses UTC day
boundaries because this backend does not yet store a per-user time zone.

To configure Google Cloud, create an OAuth 2.0 Web application client, add the
exact value of `GOOGLE_GMAIL_REDIRECT_URI` to its authorized redirect URIs, and
enable the Gmail API. Configure the client ID/secret, callback URL, and a
persistent encryption key in the backend environment. Google may require OAuth
consent-screen configuration or verification before granting Gmail read scope.
Local tests mock Google; an actual account connection requires valid Cloud
credentials and consent-screen setup.

## Deployment notes

Run Uvicorn without access logging, for example:

```powershell
uvicorn app.main:app --no-access-log
```

The Google callback carries an authorization code and state in its query string.
Disable or redact query strings in reverse-proxy and other HTTP access logs as
well; application code does not log those values. The `python -m app.main`
entry point also disables Uvicorn access logging.

The current SlowAPI limiter uses in-process memory storage. It is suitable for
single-process development, but production deployments with multiple workers or
instances should configure shared storage such as Redis before relying on these
limits. Google provider exchange and verification require valid provider
credentials and should be independently tested in the deployment environment.
