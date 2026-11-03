"""暗Ban阶段与房间拥有的截止任务，沿用房间身份和写锁。"""
from __future__ import annotations

import asyncio
import time

from ..domain import bans
from ..domain.room import RoomState
from ..infra.logging import get_logger
from .priority import room_action

logger = get_logger('card_bans')


def points_for_user(database, user_id) -> int:
    if database is None or not user_id:
        return 0
    with database.unit_of_work() as uow:
        from .ranked_seasons import RankedSeasonService
        RankedSeasonService(database).sync(uow)
        return int(uow.stats.get_rank(user_id).get('points') or 0)


class CardBanService:
    def __init__(self, rooms):
        self.rooms = rooms
        self.clock = time.time
        self.tasks: dict[str, asyncio.Task] = {}
        self.disconnect_retries: dict[tuple[str, str], asyncio.Task] = {}
        self.requeue_hook = None
        self.departure_hook = None
        self.rooms.destroy_hooks.append(self.cancel)

    def start(self, room) -> None:
        if not room.ban_enabled or len(room.players) != 2:
            return
        if room.ban_phase == 'off':
            room.ban_phase = 'countdown'
            room.ban_countdown_deadline = int((self.clock() + bans.configuration()['countdown_seconds']) * 1000)
            for pid in room.players:
                room.ban_selections.setdefault(pid, [])
        if room.id in self.tasks or not bans.pending(room):
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        task = asyncio.create_task(self._drive(room))
        self.tasks[room.id] = task
        self.rooms._tasks.add(task)
        task.add_done_callback(lambda done: self._finished(room.id, done))

    def _finished(self, room_id, task):
        self.rooms._tasks.discard(task)
        if self.tasks.get(room_id) is task:
            self.tasks.pop(room_id, None)
        if not task.cancelled() and task.exception() is not None:
            logger.error('Ban阶段任务失败', exc_info=task.exception(), extra={'room_id': room_id})

    def cancel(self, room_id):
        task = self.tasks.pop(room_id, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        for key, retry in list(self.disconnect_retries.items()):
            if key[0] == room_id:
                self.disconnect_retries.pop(key, None)
                if retry is not asyncio.current_task():
                    retry.cancel()

    def retry_disconnect(self, room, player_id, token):
        """结算事务暂时失败后重试；原掉线令牌在重连或销房后自然失效。"""
        key = (room.id, player_id)
        previous = self.disconnect_retries.get(key)
        if previous is not None and previous is not asyncio.current_task() and not previous.done():
            return

        async def retry():
            await asyncio.sleep(1)
            if self.rooms.get_room(room.id) is room:
                await self.rooms._disconnect_timeout(room.id, player_id, token)

        task = asyncio.create_task(retry())
        self.disconnect_retries[key] = task
        self.rooms._tasks.add(task)

        def finished(done):
            self.rooms._tasks.discard(done)
            if self.disconnect_retries.get(key) is done:
                self.disconnect_retries.pop(key, None)
            if not done.cancelled() and done.exception() is not None:
                logger.error('Ban掉线结算重试失败', exc_info=done.exception(), extra={'room_id': room.id})

        task.add_done_callback(finished)

    async def _drive(self, room):
        while self.rooms.get_room(room.id) is room and bans.pending(room) and room.state == RoomState.PLACING_SHIPS:
            deadline = room.ban_countdown_deadline if room.ban_phase == 'countdown' else room.ban_selection_deadline
            await asyncio.sleep(max(0, deadline / 1000 - self.clock()))
            async with room_action(room):
                await self.advance(room)

    async def advance(self, room):
        if self.rooms.get_room(room.id) is not room or room.state != RoomState.PLACING_SHIPS:
            return
        now = int(self.clock() * 1000)
        if room.ban_phase == 'countdown' and now >= room.ban_countdown_deadline:
            if room.ban_quota == 0:
                await self._reveal(room)
                return
            room.ban_phase = 'selecting'
            room.ban_selection_deadline = room.ban_countdown_deadline + bans.configuration()['selection_seconds'] * 1000
            await self.rooms.push_room_sync(room)
        if room.ban_phase == 'selecting' and now >= room.ban_selection_deadline:
            for pid in room.players:
                if pid not in room.ban_confirmed:
                    room.ban_selections[pid] = bans.timeout_selection(room.ban_selections[pid], room.ban_quota)
            await self._reveal(room)

    async def submit(self, room, player_id, data):
        await self.advance(room)
        if room.state != RoomState.PLACING_SHIPS or room.ban_phase != 'selecting':
            return {'status': 'error', 'message': '当前不在暗Ban选卡阶段'}
        if player_id in room.ban_confirmed:
            return {'status': 'error', 'message': '你已确认Ban，不能再次修改'}
        names = data.get('ban_selection')
        error = bans.validate_selection(names, room.ban_quota)
        if error:
            return {'status': 'error', 'message': error}
        confirm = data.get('ban_confirm', False)
        if type(confirm) is not bool:
            return {'status': 'error', 'message': 'Ban确认参数无效'}
        if confirm and len(names) != room.ban_quota:
            return {'status': 'error', 'message': '请先选满本局Ban名额，再确认；也可以等待超时补位'}
        room.ban_selections[player_id] = list(names)
        if confirm:
            room.ban_confirmed.add(player_id)
        if len(room.ban_confirmed) == len(room.players):
            await self._reveal(room)
        else:
            await self.rooms.push_room_sync(room)
        return {'status': 'success'}

    async def _reveal(self, room):
        room.ban_phase = 'revealed'
        room.ban_confirmed.update(room.players)
        room.banned_names = bans.merge_selections(room.ban_selections)
        bans.prune_piles(room)
        self.cancel(room.id)
        await self.rooms.push_room_sync(room)
