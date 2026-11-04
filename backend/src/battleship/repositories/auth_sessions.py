"""服务器登录会话的创建、查询和撤销。"""
from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.orm import Session

from .models import AuthSession, User


class AuthSessionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, *, session_id: str, user_id: str, credential_fingerprint: str,
               created_at: int, expires_at: int) -> None:
        self.session.add(AuthSession(id=session_id, user_id=user_id,
                                    credential_fingerprint=credential_fingerprint,
                                    created_at=created_at, expires_at=expires_at))
        self.session.flush()

    def get(self, session_id: str) -> AuthSession | None:
        return self.session.get(AuthSession, session_id)

    def revoke(self, session_id: str, *, revoked_at: int) -> None:
        self.session.execute(update(AuthSession).where(
            AuthSession.id == session_id, AuthSession.revoked_at.is_(None)
        ).values(revoked_at=revoked_at))

    def revoke_user(self, user_id: str, *, revoked_at: int) -> None:
        self.session.execute(update(AuthSession).where(
            AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
        ).values(revoked_at=revoked_at))

    def rotate_legacy_token(self, user_id: str, *, password_hash: str, token: str) -> bool:
        """写入时再次核对刚验证的凭据，避免改密后恢复旧请求的 token。"""
        result = self.session.execute(update(User).where(
            User.id == user_id, User.password_hash == password_hash
        ).values(token=token))
        return bool(result.rowcount)
