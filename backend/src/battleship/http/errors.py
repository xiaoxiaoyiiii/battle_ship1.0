"""Structured HTTP errors.

Every failure carries a stable code, a human-readable message and, for parameter
errors, the offending field. The application exception handlers turn this into
{"error": {"code": ..., "message": ..., "field": ...}} with the matching status.
"""

from __future__ import annotations

from fastapi import HTTPException

from ..services.auth import AuthError


def api_error(status_code: int, code: str, message: str,
              field: str | None = None) -> HTTPException:
    detail: dict[str, object] = {"code": code, "message": message}
    if field:
        detail["field"] = field
    return HTTPException(status_code=status_code, detail=detail)


def from_auth_error(exc: AuthError) -> HTTPException:
    return api_error(exc.status_code, exc.code, exc.message, exc.field)
