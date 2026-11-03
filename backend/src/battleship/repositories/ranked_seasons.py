"""排位季快照和当前段位缓存；只在调用方事务内操作。"""
from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from .models import BattlePassSeason, RankedSeasonState, RankedSeasonAccount, RankedSeasonResult, UserRank


def data(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


class RankedSeasonRepository:
    def __init__(self, session):
        self.session = session

    def seasons(self):
        return [data(r) for r in self.session.scalars(select(BattlePassSeason).where(
            BattlePassSeason.status == 'active').order_by(BattlePassSeason.starts_at, BattlePassSeason.id))]

    def lock(self):
        # 先写后读，跨请求、跨进程的重置和投信共享 SQLite 写锁。
        self.session.execute(update(BattlePassSeason).values(updated_at=BattlePassSeason.updated_at))

    def state(self, sid):
        row = self.session.get(RankedSeasonState, sid)
        return data(row) if row else None

    def open(self, sid, start):
        self.session.add(RankedSeasonState(season_id=sid, opened_at=start))
        self.session.flush()

    def close(self, sid, end):
        self.session.execute(update(RankedSeasonState).where(
            RankedSeasonState.season_id == sid).values(locked_at=end))
        self.session.expire_all()

    def accounts(self, sid):
        return [data(r) for r in self.session.scalars(select(RankedSeasonAccount).where(
            RankedSeasonAccount.season_id == sid).order_by(RankedSeasonAccount.points.desc(),
                RankedSeasonAccount.updated_at, RankedSeasonAccount.user_id))]

    def all_current_ranks(self):
        return [data(r) for r in self.session.scalars(select(UserRank))]

    def set_current_rank(self, uid, points, admiral, wins, losses, now):
        values = dict(user_id=uid, points=points, is_admiral=int(admiral),
                      ranked_wins=wins, ranked_losses=losses, updated_at=now)
        self.session.execute(insert(UserRank).values(**values).on_conflict_do_update(
            index_elements=['user_id'], set_={k:v for k,v in values.items() if k!='user_id'}))
        self.session.expire_all()

    def add_account(self, sid, uid, points, admiral, peak, now):
        self.session.execute(insert(RankedSeasonAccount).values(
            season_id=sid, user_id=uid, points=points, is_admiral=int(admiral),
            ranked_wins=0, ranked_losses=0, peak_tier=peak, updated_at=now,
        ).on_conflict_do_nothing(index_elements=['season_id','user_id']))

    def record(self, sid, uid, match_id, won, rank, peak, now):
        event = self.session.execute(insert(RankedSeasonResult).values(
            season_id=sid,user_id=uid,match_id=match_id,
        ).on_conflict_do_nothing(index_elements=['match_id','user_id']))
        if not event.rowcount:
            return False
        self.add_account(sid,uid,rank['points'],rank['is_admiral'],peak,now)
        row = self.session.get(RankedSeasonAccount,(sid,uid))
        row.points = rank['points']
        row.is_admiral = int(rank['is_admiral'])
        row.ranked_wins += int(won)
        row.ranked_losses += int(not won)
        row.peak_tier = max(row.peak_tier,peak)
        row.updated_at = now
        self.session.flush()
        return True

    def update_admiral_snapshot(self,sid,uid,admiral,peak):
        self.session.execute(update(RankedSeasonAccount).where(
            RankedSeasonAccount.season_id==sid,RankedSeasonAccount.user_id==uid,
        ).values(is_admiral=int(admiral),peak_tier=peak))
