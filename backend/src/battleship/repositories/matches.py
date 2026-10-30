"""matches / match_logs: history reads and match records."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, aliased

from .mapping import row_dict
from .models import Match, MatchLog, MatchReplay, User


def _load_logs(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


class MatchRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        match_id: str,
        winner_id: str | None,
        loser_id: str | None,
        timestamp: int | None,
        mode: str | None = None,
    ) -> Match:
        match = Match(
            id=match_id,
            winner_id=winner_id,
            loser_id=loser_id,
            timestamp=timestamp,
            mode=mode,
        )
        self.session.add(match)
        self.session.flush()
        return match

    def get(self, match_id: str | None) -> Match | None:
        if not match_id:
            return None
        return self.session.get(Match, match_id)

    def add_log(self, match_id: str, logs: str) -> None:
        statement = sqlite_insert(MatchLog).values(match_id=match_id, logs=logs)
        statement = statement.on_conflict_do_update(
            index_elements=["match_id"], set_={"logs": statement.excluded.logs}
        )
        self.session.execute(statement)

    def get_log(self, match_id: str) -> str | None:
        return self.session.scalar(
            select(MatchLog.logs).where(MatchLog.match_id == match_id)
        )

    def history_for_user(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Same shape as the old /user_stats history rows (without replay blobs)."""
        if not user_id:
            return []
        safe_limit = min(max(1, int(limit)), 100)
        winner = aliased(User)
        loser = aliased(User)
        has_replay = (
            select(MatchReplay.match_id)
            .where(MatchReplay.match_id == Match.id)
            .exists()
        )
        statement = (
            select(
                Match.id.label("match_id"),
                Match.winner_id,
                Match.loser_id,
                Match.timestamp,
                Match.mode,
                winner.username.label("winner_name"),
                loser.username.label("loser_name"),
                MatchLog.logs,
                has_replay.label("has_replay"),
            )
            .select_from(Match)
            .outerjoin(winner, Match.winner_id == winner.id)
            .outerjoin(loser, Match.loser_id == loser.id)
            .outerjoin(MatchLog, MatchLog.match_id == Match.id)
            .where(or_(Match.winner_id == user_id, Match.loser_id == user_id))
            .order_by(Match.timestamp.desc())
            .limit(safe_limit)
        )
        history: list[dict[str, Any]] = []
        for row in self.session.execute(statement):
            item = row_dict(row)
            item["logs"] = _load_logs(item["logs"])
            item["has_replay"] = bool(item["has_replay"])
            history.append(item)
        return history

    def recent_opponent_ids(self, user_id: str, limit: int = 10) -> list[str]:
        if not user_id:
            return []
        safe_limit = min(max(1, int(limit)), 100)
        statement = (
            select(Match.winner_id, Match.loser_id)
            .where(or_(Match.winner_id == user_id, Match.loser_id == user_id))
            .order_by(Match.timestamp.desc())
            .limit(safe_limit * 2)
        )
        opponents: list[str] = []
        for winner_id, loser_id in self.session.execute(statement):
            other = loser_id if winner_id == user_id else winner_id
            if other and other != user_id and other not in opponents:
                opponents.append(other)
            if len(opponents) >= safe_limit:
                break
        return opponents

    def consecutive_losses(self, user_id: str | None, limit: int = 50) -> int:
        """Number of consecutive losses at the head of this player's history.

        Must be read **before** the match being settled is inserted; the legacy
        streak-break bonus depends on the pre-match value.
        """

        if not user_id:
            return 0
        statement = (
            select(Match.winner_id)
            .where(or_(Match.winner_id == user_id, Match.loser_id == user_id))
            .order_by(Match.timestamp.desc())
            .limit(max(1, int(limit)))
        )
        streak = 0
        for winner_id in self.session.scalars(statement):
            if str(winner_id) == str(user_id):
                break
            streak += 1
        return streak

    def count(self) -> int:
        return int(self.session.scalar(select(func.count()).select_from(Match)) or 0)