"""HTTP 和实时入口共用的服务器会话校验，不缓存撤销状态。"""
from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any, Mapping

from ..repositories import Database
from ..repositories.unit_of_work import UnitOfWork

SESSION_ID = "auth_session_id"
SESSION_LIFETIME = 31 * 24 * 60 * 60


def credential_fingerprint(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()


def issue_session(uow: UnitOfWork, user_id: str, password_hash: str) -> str:
    session_id = secrets.token_urlsafe(32)
    now = int(time.time())
    uow.auth_sessions.create(session_id=session_id, user_id=user_id,
                             credential_fingerprint=credential_fingerprint(password_hash),
                             created_at=now, expires_at=now + SESSION_LIFETIME)
    return session_id


def has_login_identity(payload: Mapping[str, Any]) -> bool:
    return bool(payload.get("user_id") or payload.get(SESSION_ID))


def valid_session(payload: Mapping[str, Any], database: Database | None) -> bool:
    """无数据库、旧 Cookie、无记录、撤销、过期、账号删除或改密均拒绝。"""
    session_id, user_id = payload.get(SESSION_ID), payload.get("user_id")
    if database is None or not isinstance(session_id, str) or not isinstance(user_id, str):
        return False
    if not session_id or not user_id:
        return False
    with database.unit_of_work() as uow:
        record = uow.auth_sessions.get(session_id)
        if record is None or record.user_id != user_id or record.revoked_at is not None:
            return False
        if record.expires_at <= int(time.time()):
            return False
        user = uow.users.get(user_id)
        return bool(user and user.password_hash and secrets.compare_digest(
            record.credential_fingerprint, credential_fingerprint(user.password_hash)
        ))


def revoke_session(payload: Mapping[str, Any], database: Database) -> None:
    session_id = payload.get(SESSION_ID)
    if isinstance(session_id, str) and session_id:
        with database.unit_of_work() as uow:
            uow.auth_sessions.revoke(session_id, revoked_at=int(time.time()))
