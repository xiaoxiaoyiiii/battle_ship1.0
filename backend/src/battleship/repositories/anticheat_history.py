"""反作弊的有界只读历史；不调用赛季同步或复制私密回放到审计输出。"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import Match, MatchReplay

HISTORY_LIMIT = 100
LAYOUT_LIMIT = 20
MAX_REPLAY_BYTES = 512 * 1024


class AnticheatHistoryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def recent(self, user_id: str, *, before: int,
               exclude_match_id: str | None = None) -> list[dict[str, Any]]:
        statement = (
            select(Match.id, Match.winner_id, Match.loser_id, Match.timestamp,
                   Match.mode, Match.rewards_eligible)
            .where(or_(Match.winner_id == user_id, Match.loser_id == user_id),
                   Match.timestamp <= before)
            .order_by(Match.timestamp.desc(), Match.id.desc())
            .limit(HISTORY_LIMIT)
        )
        if exclude_match_id:
            statement = statement.where(Match.id != exclude_match_id)
        return [dict(row._mapping) for row in self.session.execute(statement)]

    def replays(self, match_ids: list[str]) -> list[tuple[str, dict[str, Any]]]:
        if not match_ids:
            return []
        statement = select(MatchReplay.match_id, MatchReplay.replay).where(
            MatchReplay.match_id.in_(match_ids[:HISTORY_LIMIT]),
            MatchReplay.bytes <= MAX_REPLAY_BYTES,
        ).order_by(MatchReplay.created_at.desc()).limit(LAYOUT_LIMIT)
        result = []
        for match_id, raw in self.session.execute(statement):
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if isinstance(payload, dict):
                result.append((match_id, payload))
        return result
