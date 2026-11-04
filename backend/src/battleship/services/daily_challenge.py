"""挑战用例：固定开局、持久次数、独立奖励；不调用普通比赛结算钩子。"""
from __future__ import annotations

import time
from pathlib import Path
from ..domain.daily_challenge import PuzzleCatalog, daily_window, restore_snapshot, REWARD_TIDE, REWARD_XP
from ..domain.room.models import RoomState, new_room_id
from ..infra.logging import get_logger

logger = get_logger('daily_challenge')


def release_pending_xp(uow, user_id: str, now: int) -> None:
    """赛季空档先记权益，有活跃赛季时兑付，不丢失40XP也不占对局周帽。"""
    season = uow.battle_pass.current_season(now)
    if season is None or not (int(season['starts_at']) <= now < int(season['ends_at'])):
        return
    uow.tide_ash.lock(user_id, now=now)
    for attempt in uow.daily_challenges.pending_xp(user_id):
        uow.battle_pass.add_event_once(user_id, season['id'], 'daily_challenge',
            attempt.day, REWARD_XP, now=now)
        attempt.xp_granted = 1


class DailyChallengeService:
    def __init__(self, database, rooms, path: str | Path, *, clock=None):
        self.database, self.rooms = database, rooms
        self.catalog = PuzzleCatalog(path)
        self.clock = clock or time.time
        self.battle = None
        self._launching: set[str] = set()

    def view(self, user_id: str | None) -> dict:
        now = int(self.clock())
        window = daily_window(now)
        out = {'date': window['start'], 'next_reset_at': window['next_reset_at'],
               'status': 'unavailable', 'puzzle': None, 'rewards': {'tide': REWARD_TIDE, 'xp': REWARD_XP}}
        try:
            puzzle = self.catalog.today(window['start'])
        except (ValueError, OSError) as error:
            logger.error('每日关卡配置不可用', exc_info=error)
            puzzle = None
            out['reason'] = '今日关卡配置待修复'
        if puzzle:
            out['puzzle'] = {k: puzzle[k] for k in ('puzzle_id', 'name')}
            out['puzzle']['difficulty'] = '高难 · 大师 AI'
        if not user_id:
            out['status'] = 'unauthorized'
            return out
        with self.database.unit_of_work() as uow:
            if not uow.users.get(user_id):
                out['status'] = 'unauthorized'
                return out
            attempt = uow.daily_challenges.get(user_id, window['start'])
            if attempt:
                room = self.rooms.get_room(attempt.room_id)
                if attempt.status == 'in_progress' and room is None and attempt.room_id not in self._launching:
                    # 服务重启不能恢复时按失败处理，保留已用掉的次数。
                    uow.daily_challenges.finish(user_id, attempt.day, attempt.room_id, 'failed', now)
                    out['status'] = 'failed'
                else:
                    out['status'] = attempt.status
                out['room_id'] = attempt.room_id if out['status'] == 'in_progress' else None
            elif puzzle:
                out['status'] = 'available'
        return out

    async def start(self, connection):
        uid = connection.user_id
        now = int(self.clock())
        window = daily_window(now)
        fail = lambda message: {'status': 'error', 'message': message}
        if not uid:
            return fail('请先登录，再参加每日挑战')
        denied = self.rooms._capability_denied(connection, 'play')
        if denied:
            return fail(denied)
        # 先结束该账号昨天的挑战；同日重复启动始终拒绝，继续入口走签名身份rejoin。
        for room in list(self.rooms.rooms.values()):
            if not any(self.rooms.owns_seat(connection, player) for player in room.players.values()) or room.state == RoomState.GAME_OVER:
                continue
            if room.daily_challenge and now >= room.daily_challenge['expires_at']:
                await self.expire(room)
        error = self.rooms.seating_error(connection)
        if error:
            return fail(error)
        try:
            puzzle = self.catalog.today(window['start'])
            if puzzle is None:
                return fail('今日暂无挑战')
            room = restore_snapshot(puzzle['state'], room_id=new_room_id(), user_id=uid,
                                    name=connection.username or '舰长', sid=connection.sid)
        except (ValueError, OSError) as error:
            logger.error('挑战开局校验失败', exc_info=error)
            return fail('今日挑战配置不可用，请稍后再试')
        room.daily_challenge = {'user_id': uid, 'day': window['start'], 'puzzle_id': puzzle['puzzle_id'],
                                'expires_at': window['next_reset_at']}
        room.name = puzzle['name']
        self._launching.add(room.id)
        try:
            with self.database.unit_of_work() as uow:
                if not uow.users.get(uid):
                    return fail('账号不存在，请重新登录')
                if not uow.daily_challenges.reserve(uid, window['start'], puzzle['puzzle_id'],
                                                   puzzle['sha256'], room.id, now):
                    return fail('今日挑战次数已使用，不能重开')
            # 校验、预留次数和占座之间没有 await；成功预留后才回收旧等待房。
            self.rooms.prepare_seating(connection)
            self.rooms.rooms[room.id] = room
        finally:
            self._launching.discard(room.id)
        room.issue_reconnect_token(uid)
        self.rooms._bind_presence_game(room)
        await self.rooms.rejoin_room(connection, {'room_id': room.id, 'player_id': uid})
        return {'status': 'success', 'room_id': room.id, 'player_id': uid}

    async def expire(self, room) -> bool:
        info = room.daily_challenge
        if not info or int(self.clock()) < info['expires_at']:
            return False
        if self.battle and room.state != RoomState.GAME_OVER:
            from .priority import room_action
            async with room_action(room):
                uid = info['user_id']
                other = next(pid for pid in room.players if pid != uid)
                await self.battle.finish_game(room, other, uid, reason='daily_challenge_expired')
        return True

    def settle_room(self, room, winner_id):
        from .settlement import SettlementResult
        info = room.daily_challenge
        uid, day = info['user_id'], info['day']
        now = int(self.clock())
        won = winner_id == uid and now < info['expires_at'] and not room.admin_test
        with self.database.unit_of_work() as uow:
            changed = uow.daily_challenges.finish(uid, day, room.id, 'completed' if won else 'failed', now)
            if changed and won:
                uow.tide_ash.apply_once(uid, 'daily_challenge', day, REWARD_TIDE, now=now)
                uow.tasks.increment(uid, day, 'daily_challenge')
                release_pending_xp(uow, uid, now)
        result = SettlementResult(ok=True, skipped=not changed)
        info['status'] = 'completed' if won else 'failed'
        room.settled, room.settlement_result = True, result
        return result
