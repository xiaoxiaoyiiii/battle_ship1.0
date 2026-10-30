"""FastAPI dependencies shared by the auth-owned routes.

The session is read from the signed cookie on every request; nothing is cached in
a server-side session table (the legacy stack did not have one either). The admin
gate and the capability gate are dependencies so a future router cannot forget to
call them -- forgetting to depend on a guard is the usual way authorization gets
silently dropped.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, Request

from ..config import Settings
from ..domain.anticheat import suspicion
from ..repositories import Database
from ..services.auth import AuthService
from .errors import api_error
from .session import read_session, session_user_id, session_username


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_session_data(request: Request) -> dict[str, Any]:
    return read_session(request)


def get_current_user_id(request: Request) -> str | None:
    return session_user_id(read_session(request))


def get_current_username(request: Request) -> str | None:
    return session_username(read_session(request))


def get_auth_service(
    database: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> AuthService:
    return AuthService(database, settings)


def require_user(request: Request) -> str:
    user_id = session_user_id(read_session(request))
    if not user_id:
        raise api_error(401, "unauthorized", "未登录", "session")
    return user_id


def require_admin(
    request: Request,
    service: AuthService = Depends(get_auth_service),
) -> str:
    user_id = session_user_id(read_session(request))
    if not user_id:
        raise api_error(401, "unauthorized", "未登录", "session")
    if not service.is_admin(user_id):
        # Empty DEBUG_ADMIN_USER_IDS means nobody -- never "empty means allow".
        raise api_error(403, "forbidden", "无权访问", "user_id")
    return user_id


def require_capability(capability: str) -> Callable[..., str]:
    """Dependency factory: 403 with the legacy denial text when banned."""

    def dependency(
        request: Request,
        service: AuthService = Depends(get_auth_service),
    ) -> str:
        user_id = session_user_id(read_session(request))
        if not user_id:
            raise api_error(401, "unauthorized", "未登录", "session")
        message = service.capability_denied(user_id, capability)
        if message:
            raise api_error(403, "capability_denied", message, "capability")
        return user_id

    dependency.__name__ = f"require_capability_{capability}"
    return dependency


__all__ = [
    "CAP_MATCH",
    "CAP_RANKED",
    "CAP_ROOM",
    "get_auth_service",
    "get_current_user_id",
    "get_current_username",
    "get_database",
    "get_session_data",
    "get_settings",
    "require_admin",
    "require_capability",
    "require_user",
]

CAP_RANKED = suspicion.CAP_RANKED
CAP_MATCH = suspicion.CAP_MATCH
CAP_ROOM = suspicion.CAP_ROOM
