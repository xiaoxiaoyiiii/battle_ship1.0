"""每日次数与挑战来源仅在这里读写SQL；账号与沪时日期联合主键。"""
import json
from sqlalchemy import select, update, inspect
from sqlalchemy.dialects.sqlite import insert
from .models import DailyChallengeAttempt as Attempt, DailyChallengeSource as Source, Match, MatchReplay


class DailyChallengeRepository:
    def __init__(self, session):
        self.session = session

    def get(self, user_id, day):
        return self.session.get(Attempt, (user_id, day))

    def reserve(self, user_id, day, puzzle_id, digest, room_id, now):
        result = self.session.execute(insert(Attempt).values(user_id=user_id, day=day,
            puzzle_id=puzzle_id, snapshot_hash=digest, room_id=room_id, status='in_progress',
            started_at=int(now)).on_conflict_do_nothing(index_elements=['user_id', 'day']))
        return bool(result.rowcount)

    def finish(self, user_id, day, room_id, status, now):
        result = self.session.execute(update(Attempt).where(Attempt.user_id == user_id,
            Attempt.day == day, Attempt.room_id == room_id, Attempt.status == 'in_progress')
            .values(status=status, finished_at=int(now)))
        return bool(result.rowcount)

    def pending_xp(self, user_id):
        return list(self.session.scalars(select(Attempt).where(Attempt.user_id == user_id,
            Attempt.status == 'completed', Attempt.xp_granted == 0)))

    def save_source(self, match_id, user_id, timestamp, snapshots):
        self.session.execute(insert(Source).values(match_id=match_id, user_id=user_id,
            created_at=timestamp, snapshots=json.dumps(snapshots, ensure_ascii=False))
            .on_conflict_do_nothing(index_elements=['match_id']))

    def sources(self):
        if not inspect(self.session.connection()).has_table('daily_challenge_sources'):
            return []
        return list(self.session.scalars(select(Source).order_by(Source.created_at)))

    def historical_replays(self):
        return list(self.session.execute(select(Match, MatchReplay).outerjoin(
            MatchReplay, Match.id == MatchReplay.match_id)))
