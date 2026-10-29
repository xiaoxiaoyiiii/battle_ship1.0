"""赛季通行证的事务内仓储。"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..domain.battle_pass import SeasonConfig
from .models import (
    BattlePassClaim,
    BattlePassChallengeProgress,
    BattlePassEvent,
    BattlePassLevel,
    BattlePassSeason,
    UserBattlePass,
    UserCosmeticReward,
)


class BattlePassRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_season(self, config: SeasonConfig, *, status: str = 'active', now: int | None = None) -> None:
        now = int(time.time()) if now is None else int(now)
        statement = sqlite_insert(BattlePassSeason).values(
            id=config.id, starts_at=config.starts_at, ends_at=config.ends_at,
            claim_ends_at=config.claim_ends_at, level_cap=config.level_cap,
            total_xp=config.total_xp, rules_version=config.rules_version,
            status=status, created_at=now, updated_at=now,
        )
        statement = statement.on_conflict_do_update(
            index_elements=['id'],
            set_={
                'starts_at': config.starts_at, 'ends_at': config.ends_at,
                'claim_ends_at': config.claim_ends_at, 'level_cap': config.level_cap,
                'total_xp': config.total_xp, 'rules_version': config.rules_version,
                'status': status, 'updated_at': now,
            },
        )
        self.session.execute(statement)

    def seed_level(self, season_id: str, level: int, xp_at: int,
                   free_kind: str | None, free_reward_id: str | None,
                   premium_kind: str | None, premium_reward_id: str | None) -> None:
        statement = sqlite_insert(BattlePassLevel).values(
            season_id=season_id, level=int(level), xp_at=int(xp_at),
            free_kind=free_kind, free_reward_id=free_reward_id,
            premium_kind=premium_kind, premium_reward_id=premium_reward_id,
        )
        statement = statement.on_conflict_do_update(
            index_elements=['season_id', 'level'],
            set_={'xp_at': int(xp_at), 'free_kind': free_kind,
                  'free_reward_id': free_reward_id, 'premium_kind': premium_kind,
                  'premium_reward_id': premium_reward_id},
        )
        self.session.execute(statement)

    def get_season(self, season_id: str) -> dict[str, Any] | None:
        row = self.session.get(BattlePassSeason, season_id)
        if row is None:
            return None
        return {column.name: getattr(row, column.name) for column in row.__table__.columns}

    def current_season(self, now: int) -> dict[str, Any] | None:
        row = self.session.execute(
            select(BattlePassSeason).where(
                BattlePassSeason.starts_at <= int(now),
                BattlePassSeason.claim_ends_at > int(now),
            ).order_by(BattlePassSeason.starts_at.desc()).limit(1)
        ).scalar_one_or_none()
        if row is None:
            return None
        return {column.name: getattr(row, column.name) for column in row.__table__.columns}

    def latest_season(self) -> dict[str, Any] | None:
        row = self.session.execute(
            select(BattlePassSeason).order_by(BattlePassSeason.starts_at.desc()).limit(1)
        ).scalar_one_or_none()
        if row is None:
            return None
        return {column.name: getattr(row, column.name) for column in row.__table__.columns}

    def levels(self, season_id: str) -> list[dict[str, Any]]:
        rows = self.session.execute(
            select(BattlePassLevel).where(BattlePassLevel.season_id == season_id)
            .order_by(BattlePassLevel.level)
        ).scalars()
        return [{column.name: getattr(row, column.name) for column in row.__table__.columns}
                for row in rows]

    def progress(self, user_id: str, season_id: str, *, now: int | None = None) -> dict[str, Any]:
        now = int(time.time()) if now is None else int(now)
        row = self.session.get(UserBattlePass, (user_id, season_id))
        if row is None:
            return {'user_id': user_id, 'season_id': season_id, 'xp': 0,
                    'premium_unlocked': False, 'version': 0, 'created_at': now,
                    'updated_at': now}
        return {column.name: getattr(row, column.name) for column in row.__table__.columns} | {
            'premium_unlocked': bool(row.premium_unlocked),
        }

    def _ensure_progress(self, user_id: str, season_id: str, now: int) -> UserBattlePass:
        row = self.session.get(UserBattlePass, (user_id, season_id))
        if row is None:
            row = UserBattlePass(user_id=user_id, season_id=season_id, xp=0,
                                 premium_unlocked=0, version=0, created_at=now, updated_at=now)
            self.session.add(row)
            self.session.flush()
        return row

    def add_event_once(self, user_id: str, season_id: str, source_kind: str,
                       source_id: str, xp_delta: int, *, payload_hash: str | None = None,
                       now: int | None = None) -> bool:
        now = int(time.time()) if now is None else int(now)
        statement = sqlite_insert(BattlePassEvent).values(
            user_id=user_id, season_id=season_id, source_kind=source_kind,
            source_id=source_id, xp_delta=max(0, int(xp_delta)),
            payload_hash=payload_hash, created_at=now,
        ).on_conflict_do_nothing(
            index_elements=['user_id', 'season_id', 'source_kind', 'source_id']
        )
        result = self.session.execute(statement)
        if not result.rowcount:
            return False
        row = self._ensure_progress(user_id, season_id, now)
        row.xp = max(0, int(row.xp or 0) + max(0, int(xp_delta)))
        row.version = int(row.version or 0) + 1
        row.updated_at = now
        self.session.flush()
        return True

    def unlock_premium(self, user_id: str, season_id: str, *, now: int | None = None) -> bool:
        now = int(time.time()) if now is None else int(now)
        row = self._ensure_progress(user_id, season_id, now)
        if row.premium_unlocked:
            return False
        row.premium_unlocked = 1
        row.version = int(row.version or 0) + 1
        row.updated_at = now
        self.session.flush()
        return True

    def claim_once(self, user_id: str, season_id: str, level: int, track: str,
                   reward_kind: str, reward_id: str, grant_key: str,
                   *, now: int | None = None) -> bool:
        now = int(time.time()) if now is None else int(now)
        statement = sqlite_insert(BattlePassClaim).values(
            user_id=user_id, season_id=season_id, level=int(level), track=track,
            reward_kind=reward_kind, reward_id=reward_id, grant_key=grant_key,
            claimed_at=now,
        ).on_conflict_do_nothing(
            index_elements=['user_id', 'season_id', 'level', 'track']
        )
        result = self.session.execute(statement)
        if not result.rowcount:
            return False
        reward = sqlite_insert(UserCosmeticReward).values(
            user_id=user_id, kind=reward_kind, reward_id=reward_id,
            source_season_id=season_id, source_level=int(level),
            source_track=track, granted_at=now,
        ).on_conflict_do_nothing(index_elements=['user_id', 'kind', 'reward_id'])
        self.session.execute(reward)
        return True

    def claims(self, user_id: str, season_id: str) -> list[dict[str, Any]]:
        rows = self.session.execute(
            select(BattlePassClaim).where(
                BattlePassClaim.user_id == user_id,
                BattlePassClaim.season_id == season_id,
            ).order_by(BattlePassClaim.level, BattlePassClaim.track)
        ).scalars()
        return [{column.name: getattr(row, column.name) for column in row.__table__.columns}
                for row in rows]

    def cosmetic_rewards(self, user_id: str) -> set[tuple[str, str]]:
        rows = self.session.execute(
            select(UserCosmeticReward.kind, UserCosmeticReward.reward_id)
            .where(UserCosmeticReward.user_id == user_id)
        )
        return {(str(kind), str(reward_id)) for kind, reward_id in rows}

    def challenge_progress(self, user_id: str, season_id: str) -> list[dict[str, Any]]:
        rows = self.session.execute(
            select(BattlePassChallengeProgress).where(
                BattlePassChallengeProgress.user_id == user_id,
                BattlePassChallengeProgress.season_id == season_id,
            ).order_by(BattlePassChallengeProgress.challenge_id)
        ).scalars()
        return [{column.name: getattr(row, column.name) for column in row.__table__.columns}
                for row in rows]

    def add_challenge_progress(self, user_id: str, season_id: str,
                               challenge_id: str, delta: int, target: int,
                               *, now: int | None = None) -> tuple[int, bool]:
        """增加挑战进度并返回 ``(累计值, 本次是否首次完成)``。"""
        delta = max(0, int(delta))
        target = max(1, int(target))
        now = int(time.time()) if now is None else int(now)
        row = self.session.get(BattlePassChallengeProgress,
                               (user_id, season_id, challenge_id))
        if row is None:
            row = BattlePassChallengeProgress(
                user_id=user_id, season_id=season_id, challenge_id=challenge_id,
                progress=0, completed_at=None, updated_at=now,
            )
            self.session.add(row)
            self.session.flush()
        before = int(row.progress or 0)
        row.progress = before + delta
        row.updated_at = now
        newly_completed = row.completed_at is None and row.progress >= target
        if newly_completed:
            row.completed_at = now
        self.session.flush()
        return int(row.progress), bool(newly_completed)
