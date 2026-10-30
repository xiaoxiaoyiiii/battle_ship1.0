"""Authentication use cases: accounts, sessions, admin identity and bans.

The HTTP layer only adapts requests; every policy decision lives here:

* registration rules and duplicate handling;
* password verification through werkzeug (legacy hashes remain valid);
* token issuance for the frozen POST /api/login contract;
* admin identity from DEBUG_ADMIN_USER_IDS (an empty list means nobody);
* effective ban level, always derived from match_suspicion + admin override.

No SQL is written here -- all persistence goes through the ticket #5 UnitOfWork
and its repositories.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

from ..config import Settings
from ..domain.anticheat import suspicion
from ..repositories import Database

USERNAME_MIN_LENGTH = 3
PASSWORD_MIN_LENGTH = 6
_USERNAME_ALLOWED_EXTRA = "._-"


class AuthError(Exception):
    """A user-facing auth failure with a stable code and an optional field."""

    def __init__(self, status_code: int, code: str, message: str,
                 field: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field = field


def normalize_username(username: Any) -> str:
    return str(username or "").strip()


def validate_username(username: str) -> None:
    if not username:
        raise AuthError(400, "validation_error", "用户名不能为空", "username")
    if len(username) < USERNAME_MIN_LENGTH:
        raise AuthError(400, "validation_error",
                        f"用户名长度至少 {USERNAME_MIN_LENGTH} 位", "username")
    if not all(char.isalnum() or char in _USERNAME_ALLOWED_EXTRA for char in username):
        raise AuthError(400, "validation_error",
                        "用户名只能包含字母、数字、点、下划线和短横线", "username")


def validate_password(password: str, *, field: str = "password") -> None:
    if not password:
        raise AuthError(400, "validation_error", "密码不能为空", field)
    if len(password) < PASSWORD_MIN_LENGTH:
        raise AuthError(400, "validation_error",
                        f"密码长度至少 {PASSWORD_MIN_LENGTH} 位", field)


class AuthService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    # ---------------------------------------------------------------- accounts

    def register(self, username: Any, password: Any) -> dict[str, str]:
        name = normalize_username(username)
        validate_username(name)
        raw_password = str(password or "")
        validate_password(raw_password)

        password_hash = generate_password_hash(raw_password)
        user_id = str(uuid.uuid4())
        with self.database.unit_of_work() as uow:
            if uow.users.get_by_username(name) is not None:
                raise AuthError(409, "username_taken", "用户名已存在", "username")
            try:
                user = uow.users.create(
                    user_id=user_id,
                    username=name,
                    password_hash=password_hash,
                )
            except Exception as exc:  # unique race between the check and the insert
                if "UNIQUE" in str(exc).upper():
                    raise AuthError(409, "username_taken", "用户名已存在", "username") from exc
                raise
        return {"id": user.id, "username": user.username}

    def authenticate(self, username: Any, password: Any) -> dict[str, str] | None:
        name = normalize_username(username)
        if not name or not password:
            return None
        with self.database.unit_of_work() as uow:
            user = uow.users.get_by_username(name)
            if user is None or not user.password_hash:
                return None
            try:
                matches = check_password_hash(user.password_hash, str(password))
            except (ValueError, TypeError):
                return None
            if not matches:
                return None
            return {"id": str(user.id), "username": str(user.username or name)}

    def issue_token(self, username: Any, password: Any) -> str:
        """Frozen POST /api/login: verify, then rotate the legacy users.token."""
        identity = self.authenticate(username, password)
        if identity is None:
            raise AuthError(401, "invalid_credentials", "用户名或密码错误")
        token = str(uuid.uuid4())
        with self.database.unit_of_work() as uow:
            updated = uow.users.update(identity["id"], token=token)
        if not updated:
            raise AuthError(500, "token_issue_failed", "登录失败")
        return token

    def change_password(self, user_id: str | None, old_password: Any,
                        new_password: Any) -> None:
        if not user_id:
            raise AuthError(401, "unauthorized", "未登录", "session")
        old = str(old_password or "")
        new = str(new_password or "")
        if not old:
            raise AuthError(400, "validation_error", "请填写原密码", "old_password")
        if not new:
            raise AuthError(400, "validation_error", "请填写新密码", "new_password")

        with self.database.unit_of_work() as uow:
            user = uow.users.get(user_id)
            if user is None or not user.password_hash:
                raise AuthError(401, "unauthorized", "账号不存在", "session")
            try:
                matches = check_password_hash(user.password_hash, old)
            except (ValueError, TypeError):
                matches = False
            if not matches:
                raise AuthError(403, "invalid_old_password", "原密码错误", "old_password")
            if len(new) < PASSWORD_MIN_LENGTH:
                raise AuthError(400, "validation_error",
                                f"新密码长度至少{PASSWORD_MIN_LENGTH}位", "new_password")
            updated = uow.users.update(user_id, password_hash=generate_password_hash(new))
            if not updated:
                raise AuthError(500, "password_update_failed", "修改失败")

    # ------------------------------------------------------------------ admin

    def is_admin(self, user_id: str | None) -> bool:
        """DEBUG_ADMIN_USER_IDS semantics: empty means nobody is an admin."""
        if not user_id:
            return False
        return str(user_id) in self.settings.debug_admin_user_ids

    # ------------------------------------------------------------------- bans

    def suspicion_matches(self, user_id: str) -> list[dict[str, Any]]:
        with self.database.unit_of_work() as uow:
            rows = uow.stats.list_suspicions(user_id, limit=500)
        now = time.time()
        return [
            {
                "score": row.get("score"),
                "age_days": suspicion.match_age_days(row.get("created_at"), now),
            }
            for row in rows
        ]

    def suspicion_level(self, user_id: str | None) -> int:
        """Effective level derived from stored scores + override; never stored."""
        if not user_id:
            return suspicion.LEVEL_NONE
        matches = self.suspicion_matches(user_id)
        with self.database.unit_of_work() as uow:
            override = uow.stats.latest_override(user_id)
        return suspicion.effective_level(suspicion.accumulate(matches), override)

    def capability_denied(self, user_id: str | None, capability: str) -> str:
        """Empty string means allowed; otherwise the player-facing refusal text."""
        return suspicion.denial_message(self.suspicion_level(user_id), capability)
