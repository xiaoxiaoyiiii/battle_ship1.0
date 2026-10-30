"""users table: accounts, tokens and win/loss counters."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .models import User

USER_COLUMNS = frozenset(
    {
        "username",
        "password_hash",
        "wins",
        "losses",
        "current_streak",
        "longest_streak",
        "created_at",
        "signature",
        "avatar",
        "token",
    }
)


class UserUpdateError(ValueError):
    """The caller tried to update a column that is not part of the users table."""


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, user_id: str | None) -> User | None:
        if not user_id:
            return None
        return self.session.get(User, user_id)

    def get_by_username(self, username: str | None) -> User | None:
        if not username:
            return None
        return self.session.scalar(select(User).where(User.username == username))

    def get_by_token(self, token: str | None) -> User | None:
        if not token:
            return None
        return self.session.scalar(select(User).where(User.token == token))

    def list_by_ids(self, user_ids: list[str]) -> dict[str, User]:
        ids = [user_id for user_id in user_ids if user_id]
        if not ids:
            return {}
        rows = self.session.scalars(select(User).where(User.id.in_(ids))).all()
        return {row.id: row for row in rows}

    def create(
        self,
        *,
        user_id: str,
        username: str,
        password_hash: str,
        token: str = "",
        created_at: int | None = None,
    ) -> User:
        user = User(
            id=user_id,
            username=username,
            password_hash=password_hash,
            wins=0,
            losses=0,
            current_streak=0,
            longest_streak=0,
            created_at=int(time.time()) if created_at is None else int(created_at),
            signature="",
            avatar="",
            token=token,
        )
        self.session.add(user)
        self.session.flush()
        return user

    def update(self, user_id: str, **fields: object) -> bool:
        unknown = set(fields) - USER_COLUMNS
        if unknown:
            raise UserUpdateError(f"unknown users columns: {sorted(unknown)}")
        if not fields or not user_id:
            return False
        result = self.session.execute(
            update(User).where(User.id == user_id).values(**fields)
        )
        return bool(result.rowcount)

    def wins_rank(self, user_id: str | None) -> int | None:
        """Legacy achievements rank: wins DESC, longest_streak DESC, played only.

        Mirrors db.get_user_rank (not the rank leaderboard, which is points based).
        Returns None when the account does not exist.
        """

        from sqlalchemy import func

        if not user_id:
            return None
        row = self.session.execute(
            select(User.wins, User.longest_streak).where(User.id == user_id)
        ).first()
        if row is None:
            return None
        wins = int(row.wins or 0)
        longest = int(row.longest_streak or 0)
        ahead = self.session.scalar(
            select(func.count())
            .select_from(User)
            .where(
                (func.coalesce(User.wins, 0) + func.coalesce(User.losses, 0)) > 0,
                (func.coalesce(User.wins, 0) > wins)
                | (
                    (func.coalesce(User.wins, 0) == wins)
                    & (func.coalesce(User.longest_streak, 0) > longest)
                ),
            )
        )
        return int(ahead or 0) + 1

    def leaderboard(self, limit: int = 100) -> list[dict[str, Any]]:
        """Wins board: only accounts that have played, wins DESC then streak DESC."""
        from sqlalchemy import func

        safe_limit = min(max(1, int(limit)), 100)
        statement = (
            select(
                User.id,
                User.username,
                User.wins,
                User.losses,
                User.current_streak,
                User.longest_streak,
                User.avatar,
            )
            .where(
                (func.coalesce(User.wins, 0) + func.coalesce(User.losses, 0)) > 0
            )
            .order_by(User.wins.desc(), User.longest_streak.desc())
            .limit(safe_limit)
        )
        return [dict(row._mapping) for row in self.session.execute(statement)]

    def count(self) -> int:
        from sqlalchemy import func

        return int(self.session.scalar(select(func.count()).select_from(User)) or 0)