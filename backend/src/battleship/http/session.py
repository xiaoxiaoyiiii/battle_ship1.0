"""Signed cookie sessions for the migration window.

The old stack used Flask's signed session cookie and only two keys: user_id and
username (plus Flask's internal _flashes). This module keeps the same cookie name
and keys, but signs with itsdangerous directly because the new stack has no Flask.

Security contract (DECISIONS D13):

* HttpOnly always;
* SameSite=Lax is the CSRF mitigation -- there is deliberately NO token based
  CSRF, because the legacy frontend has no token and must keep working during
  Phase 2;
* Secure is added only when the request itself arrived over HTTPS (or a trusted
  reverse proxy says so through X-Forwarded-Proto).

The value is a URL-safe timed signature. A tampered or expired cookie loads as an
empty session; callers never see an exception.
"""

from __future__ import annotations

from typing import Any, Mapping

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.requests import Request
from starlette.responses import Response

SESSION_COOKIE_NAME = "session"
SESSION_USER_ID = "user_id"
SESSION_USERNAME = "username"
SESSION_FLASHES = "_flashes"
SESSION_SALT = "battleship-session"
SESSION_MAX_AGE_SECONDS = 31 * 24 * 60 * 60  # Flask's default permanent lifetime


class SessionCodec:
    """Serialize/deserialize the signed session payload."""

    def __init__(self, secret_key: str, *, salt: str = SESSION_SALT,
                 max_age: int = SESSION_MAX_AGE_SECONDS) -> None:
        self._serializer = URLSafeTimedSerializer(secret_key, salt=salt)
        self.max_age = max_age

    def loads(self, raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            data = self._serializer.loads(raw, max_age=self.max_age)
        except (BadSignature, SignatureExpired, ValueError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    def is_valid(self, raw: str | None) -> bool:
        """True when the cookie is a live signed payload (even an empty one).

        A signed empty session is what logout leaves behind; only an unreadable
        or expired cookie means "the browser is carrying the old stack's cookie".
        """
        if not raw:
            return False
        try:
            self._serializer.loads(raw, max_age=self.max_age)
        except (BadSignature, SignatureExpired, ValueError, TypeError):
            return False
        return True

    def dumps(self, data: Mapping[str, Any]) -> str:
        return self._serializer.dumps(dict(data))


def parse_cookie_header(raw: str | None) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for part in (raw or "").split(";"):
        name, separator, value = part.partition("=")
        if not separator:
            continue
        name = name.strip()
        if name:
            cookies[name] = value.strip()
    return cookies


def _codec(request: Request) -> SessionCodec:
    settings = request.app.state.settings
    return SessionCodec(settings.secret_key.get_secret_value())


def raw_session_cookie(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE_NAME)


def read_session(request: Request) -> dict[str, Any]:
    return _codec(request).loads(raw_session_cookie(request))


def session_cookie_invalid(request: Request) -> bool:
    """The request carries a session cookie this stack cannot verify.

    Phase 2 invalidates every cookie signed by the legacy stack (different
    serialization).  Pages use this to show the re-login notice instead of
    silently rendering an anonymous screen.
    """
    raw = raw_session_cookie(request)
    return bool(raw) and not _codec(request).is_valid(raw)


def session_from_cookie_header(secret_key: str, raw_cookie_header: str | None) -> dict[str, Any]:
    """Use from Socket.IO's handshake environ (there is no Request object)."""

    cookies = parse_cookie_header(raw_cookie_header)
    return SessionCodec(secret_key).loads(cookies.get(SESSION_COOKIE_NAME))


def is_secure_request(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    forwarded = (request.headers.get("x-forwarded-proto") or "").split(",", 1)[0].strip().lower()
    return forwarded == "https"


def write_session(response: Response, request: Request, data: Mapping[str, Any]) -> None:
    cookie = _codec(request).dumps(data)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        cookie,
        path="/",
        httponly=True,
        samesite="lax",
        secure=is_secure_request(request),
    )


def clear_session(response: Response, request: Request) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=is_secure_request(request),
    )


def flash(data: dict[str, Any], message: str, category: str = "message") -> dict[str, Any]:
    """Append a legacy flash entry to a mutable session payload."""

    messages = list(data.get(SESSION_FLASHES) or [])
    messages.append([category, message])
    data[SESSION_FLASHES] = messages
    return data


def pop_flashes(data: dict[str, Any]) -> list[tuple[str, str]]:
    raw = data.pop(SESSION_FLASHES, None)
    result: list[tuple[str, str]] = []
    for item in raw or ():
        if isinstance(item, (list, tuple)) and len(item) == 2:
            result.append((str(item[0]), str(item[1])))
    return result


def session_user_id(data: Mapping[str, Any]) -> str | None:
    value = data.get(SESSION_USER_ID)
    return str(value) if value else None


def session_username(data: Mapping[str, Any]) -> str | None:
    value = data.get(SESSION_USERNAME)
    return str(value) if value else None
