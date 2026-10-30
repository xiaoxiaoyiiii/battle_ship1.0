"""match_replays: replay blobs with participant-based access metadata."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .mapping import instance_dict
from .models import MatchReplay


class ReplayRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(
        self,
        match_id: str,
        replay: Any,
        *,
        winner_user_id: str | None,
        loser_user_id: str | None,
        created_at: int,
        version: int | None = None,
    ) -> bool:
        """Insert/replace one replay. Returns False when nobody could ever read it."""
        if not match_id:
            return False
        if not winner_user_id and not loser_user_id:
            return False
        blob = replay if isinstance(replay, str) else json.dumps(
            replay, ensure_ascii=False, separators=(",", ":")
        )
        if version is None:
            version = 0
            try:
                version = int((json.loads(blob) or {}).get("version") or 0)
            except (TypeError, ValueError):
                version = 0
        values = {
            "match_id": match_id,
            "winner_user_id": winner_user_id or None,
            "loser_user_id": loser_user_id or None,
            "created_at": created_at,
            "bytes": len(blob.encode("utf-8")),
            "version": version,
            "replay": blob,
        }
        statement = sqlite_insert(MatchReplay).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["match_id"],
            set_={key: statement.excluded[key] for key in values if key != "match_id"},
        )
        self.session.execute(statement)
        return True

    def get(self, match_id: str | None) -> dict[str, Any] | None:
        if not match_id:
            return None
        replay = self.session.get(MatchReplay, match_id)
        return instance_dict(replay) if replay is not None else None

    def has(self, match_id: str) -> bool:
        return bool(
            self.session.scalar(
                select(func.count())
                .select_from(MatchReplay)
                .where(MatchReplay.match_id == match_id)
            )
        )

    def delete(self, match_id: str) -> bool:
        result = self.session.execute(
            delete(MatchReplay).where(MatchReplay.match_id == match_id)
        )
        return bool(result.rowcount)

    def recent_match_ids_for_user(self, user_id: str, limit: int) -> list[str]:
        if not user_id:
            return []
        statement = (
            select(MatchReplay.match_id)
            .where(
                (MatchReplay.winner_user_id == user_id)
                | (MatchReplay.loser_user_id == user_id)
            )
            .order_by(MatchReplay.created_at.desc())
            .limit(max(1, int(limit)))
        )
        return list(self.session.scalars(statement))