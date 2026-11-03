"""通行证配置即排位季配置；在边界前锁榜，在新季一次性重置及投信。"""
import time
from ..domain.progression import ranks
from ..domain.ranked_seasons import reset_points, tier_index, season_rewards, MIN_GAMES, CLAIM_SECONDS
from .mailbox import validate_attachments


def _admirals(rows):
    """只用该季快照计算船长池，历史榜不借用新季的名次。"""
    pool=[row for row in rows if row['points']>=ranks.CAPTAIN_FLOOR
          and row['ranked_wins']+row['ranked_losses']>0]
    positions={row['user_id']:position for position,row in enumerate(pool,1)}
    return {row['user_id']:ranks.is_admiral(row,positions.get(row['user_id']),len(pool)) for row in rows}


class RankedSeasonService:
    def __init__(self,database):
        self.database=database

    def sync(self,uow,*,now=None):
        now=int(time.time()) if now is None else int(now)
        repo=uow.ranked_seasons
        seasons=[s for s in repo.seasons() if s['starts_at']<=now]
        pending=any(not repo.state(s['id']) or (s['ends_at']<=now and not repo.state(s['id'])['locked_at']) for s in seasons)
        if pending:
            repo.lock()
            previous=None
            for season in seasons:
                sid=season['id']
                if repo.state(sid) is None:
                    repo.open(sid,season['starts_at'])
                    if previous:
                        for row in repo.accounts(previous['id']):
                            uid=row['user_id']
                            games=row['ranked_wins']+row['ranked_losses']
                            points=reset_points(row['points'],bool(row['is_admiral']),games)
                            repo.set_current_rank(uid,points,False,0,0,season['starts_at'])
                            repo.add_account(sid,uid,points,False,tier_index(points),season['starts_at'])
                            if games>=MIN_GAMES:
                                uow.mailbox.deliver(uid,f'ranked:{previous["id"]}',
                                    f'{previous["id"]} 赛季结算奖励',
                                    f'本季最高段位：{ranks.TIERS[row["peak_tier"]]["name"]}。感谢出战！请在新季开始后 14 天内领取附件。',
                                    validate_attachments(season_rewards(row['peak_tier'])),season['starts_at'],
                                    season['starts_at']+30*86400,season['starts_at']+CLAIM_SECONDS)
                    else:
                        for row in repo.all_current_ranks():
                            repo.set_current_rank(row['user_id'],row['points'],bool(row['is_admiral']),0,0,season['starts_at'])
                            repo.add_account(sid,row['user_id'],row['points'],row['is_admiral'],
                                tier_index(row['points'],bool(row['is_admiral'])),season['starts_at'])
                if season['ends_at']<=now and repo.state(sid)['locked_at'] is None:
                    self.refresh_admirals(uow,sid)
                    repo.close(sid,season['ends_at'])
                previous=season
        return next((s for s in reversed(seasons) if now<s['ends_at']
                     and repo.state(s['id'])['locked_at'] is None),None)

    def current(self,*,now=None):
        with self.database.unit_of_work() as uow:
            return self.sync(uow,now=now)

    def record_result(self,uow,sid,uid,won,*,now=None,match_id=None,before_tier=None,refresh=True):
        now=int(time.time()) if now is None else int(now)
        current=self.sync(uow,now=now)
        if current is None or current['id']!=sid:
            return False
        row=uow.stats.get_rank(uid)
        peak=max(tier_index(row['points'],bool(row['is_admiral'])),before_tier or 0)
        recorded=uow.ranked_seasons.record(sid,uid,str(match_id or f'{sid}:{uid}:{now}'),won,row,peak,now)
        if recorded and refresh:
            self.refresh_admirals(uow,sid)
        return recorded

    def refresh_admirals(self,uow,sid):
        """双方结果完整落盘后刷新动态晋升与最高段位，锁榜后禁止刷新。"""
        state=uow.ranked_seasons.state(sid)
        if state is None or state['locked_at'] is not None:
            return
        rows=uow.ranked_seasons.accounts(sid)
        verdicts=_admirals(rows)
        for row in rows:
            admiral=verdicts[row['user_id']]
            peak=max(row['peak_tier'],8 if admiral else 0)
            if bool(row['is_admiral'])!=admiral or row['peak_tier']!=peak:
                uow.ranked_seasons.update_admiral_snapshot(sid,row['user_id'],admiral,peak)

    def leaderboard(self,sid=None,*,now=None,limit=100,offset=0,user_id=None):
        now=int(time.time()) if now is None else int(now)
        with self.database.unit_of_work() as uow:
            current=self.sync(uow,now=now)
            seasons=uow.ranked_seasons.seasons()
            selected=next((s for s in seasons if s['id']==sid),None) if sid else current or next(
                (s for s in reversed(seasons) if s['starts_at']<=now),None)
            if selected is None:
                return {'leaderboard':[],'total':0,'my_rank':None,'season':None,'seasons':seasons,'constants':ranks.constants()}
            rows=uow.ranked_seasons.accounts(selected['id'])
            # 未出战的新季重置落点可展示在个人资料，不占本季榜单。
            rows=[r for r in rows if r['ranked_wins']+r['ranked_losses']>0]
            state=uow.ranked_seasons.state(selected['id'])
            locked=bool(state and state['locked_at'] is not None) or now>=selected['ends_at']
            admirals={r['user_id']:bool(r['is_admiral']) for r in rows} if locked else _admirals(rows)
            users=uow.users.list_by_ids([r['user_id'] for r in rows])
            board=[]
            my_rank=None
            for position,row in enumerate(rows,1):
                if row['user_id']==user_id: my_rank=position
                user=users.get(row['user_id'])
                board.append({**row,**ranks.rank_view(row['points'],is_admiral=admirals[row['user_id']],server_rank=position),
                    'username':getattr(user,'username',''),'avatar':getattr(user,'avatar',''),'position':position})
            return {'leaderboard':board[offset:offset+limit],'total':len(board),'my_rank':my_rank,
                'season':{**selected,'locked':locked},'seasons':seasons,'constants':ranks.constants()}
