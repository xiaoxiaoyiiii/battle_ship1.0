"""阶段转换询问：一个请求、一个期限，响应结算后只续做一次。"""
from __future__ import annotations

import asyncio
import functools
import time
from contextlib import asynccontextmanager
from typing import Any

from ..domain.magic.chain import usable_speed3_cards
from ..domain.magic.precheck import steal_error
from ..domain.magic.interaction import pending_action_reason, placement_blocked_cells
from ..domain.room import Room, RoomState, alive_ships, card_payload
from ..domain.room.sync import priority_payload
from .rooms import Connection

PRIORITY_SECONDS = 10


@asynccontextmanager
async def room_action(room: Room):
    """同一房间串行写入；同一任务内部的出牌、结算、阶段续做允许重入。"""
    gate = getattr(room, '_action_gate', None)
    if gate is None:
        gate = {'lock': asyncio.Lock(), 'owner': None}
        room._action_gate = gate
    task = asyncio.current_task()
    if gate['owner'] is task:
        yield
        return
    async with gate['lock']:
        gate['owner'] = task
        try:
            yield
        finally:
            gate['owner'] = None


def guard_phase_write(method=None, *, allow_priority=False):
    """棋盘写入口共用串行锁与等待闸门；投降串行提交但不受等待限制。"""
    if method is None:
        return lambda wrapped: guard_phase_write(wrapped, allow_priority=allow_priority)
    @functools.wraps(method)
    async def guarded(self, *args, **kwargs):
        connection = args[0] if args else kwargs.get('connection')
        data = args[1] if len(args) > 1 else kwargs.get('data')
        payload = connection if isinstance(connection, dict) else (data if isinstance(data, dict) else {})
        room = connection if isinstance(connection, Room) else self.rooms.get_room(payload.get('room_id'))
        if room is None:
            return await method(self, *args, **kwargs)
        async with room_action(room):
            if room.priority_pending and not allow_priority:
                return {'status': 'error', 'message': '阶段转换询问中，请先完成响应或等待对方回答'}
            return await method(self, *args, **kwargs)
    return guarded


class PhasePriority:
    def __init__(self, gameplay):
        self.gameplay = gameplay
        self.seconds = PRIORITY_SECONDS
        self._resuming: set[str] = set()

    @property
    def rooms(self):
        return self.gameplay.rooms

    async def _emit(self, event, data, **target):
        await self.gameplay._publisher.emit(event, data, **target)

    @staticmethod
    def cards(room: Room, responder: str):
        """无连锁的阶段时点：再剔除没有合法效果对象的速阶三。"""
        player = room.players[responder]
        alive = alive_ships(player)
        result = []
        for card in usable_speed3_cards(room, responder):
            name = card.name
            if name == '平等条约':
                continue  # 本询问尚无可无效的船数变化连锁项。
            if name == '盗亦有道' and steal_error(room, responder):
                continue
            if name in ('死者苏生', '疗愈') and not player.sunken_ships:
                continue
            if name == '神之宣告' and (player.remaining_ships <= 2 or len(alive) < 2):
                continue
            if name == '绝处逢生' and player.remaining_ships < 3:
                continue
            if name == '钢筋铁骨' and (player.remaining_ships < 2 or len(alive) < 2):
                continue
            if name == '八方来财' and getattr(room.current_phase, 'value', room.current_phase) != 'preparation':
                continue
            if name in ('增援', '死者苏生') and len(placement_blocked_cells(room, responder)) >= 36:
                continue
            if name in ('失灵！', '加百列之光') and not room.field_magic:
                last = room.magic_history[-1] if room.magic_history else None
                if not last or last.get('caster') == responder:
                    continue
                if name == '失灵！' and (
                    last.get('round', room.round) != room.round
                    or getattr(last.get('card'), 'name', None) in ('看破！', '加百列之光')
                ):
                    continue
            result.append(card)
        return result

    async def request(self, room: Room, actor: str, action: str) -> bool:
        responder = room.opponent_of(actor)
        magic = self.gameplay.magic
        if (magic is None or not responder or responder.startswith('ai-')
                or room.disconnected or room.chain or room.chain_waiting or room.chain_resolving
                or room.priority_pending or room.priority_continue
                or room.decline_priority.get(responder)
                or not room.players[responder].socket_id
                or pending_action_reason(room, actor)):
            return False
        player = room.players[responder]
        if player.magic_blocked:
            return False
        cards = self.cards(room, responder)
        if not cards:
            return False
        room.priority_token += 1
        token = room.priority_token
        room.priority_pending = {
            'token': token, 'actor': actor, 'responder': responder, 'action': action,
            'round': room.round, 'phase': getattr(room.current_phase, 'value', room.current_phase),
            'speed3_cards': [card_payload(card) for card in cards],
            'countdown': self.seconds, 'deadline': int((time.time() + self.seconds) * 1000),
        }
        magic.priority_continue_hook = self.continue_after_chain
        # 状态在第一个 await 前建立，第二个转换请求不能插队或推进阶段。
        await self._emit('priority_request', priority_payload(room, responder), to=player.socket_id)
        await self._emit('priority_waiting', priority_payload(room, actor), to=room.players[actor].socket_id)
        magic.timers.spawn(room.id, self._timeout(room, token))
        return True

    async def _timeout(self, room: Room, token: int):
        pending = room.priority_pending
        if not pending or pending['token'] != token:
            return
        await asyncio.sleep(max(0, (pending['deadline'] - time.time() * 1000) / 1000))
        if self.rooms.get_room(room.id) is room and room.priority_pending and room.priority_pending['token'] == token:
            async with room_action(room):
                if room.priority_pending and room.priority_pending['token'] == token:
                    await self._pass(room)

    async def _end_window(self, room: Room, pending: dict):
        for pid in (pending['actor'], pending['responder']):
            if pid in room.players and room.players[pid].socket_id:
                await self._emit('priority_waiting_end', {'token': pending['token']}, to=room.players[pid].socket_id)

    async def _pass(self, room: Room):
        pending = room.priority_pending
        if not pending:
            return
        room.priority_pending = None
        room.priority_continue = {**pending, 'ready': True}
        await self._end_window(room, pending)
        await self.continue_after_chain(room, room.priority_continue)

    async def decline(self, room: Room, player_id: str):
        async with room_action(room):
            if room.priority_pending and room.priority_pending.get('responder') == player_id:
                await self._pass(room)

    async def response(self, connection: Connection, data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room = self.rooms.get_room((data or {}).get('room_id'))
        if room is None:
            return {'status': 'error', 'message': '无效的房间或玩家'}
        async with room_action(room):
            return await self._respond(connection, data)

    async def _respond(self, connection: Connection, data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room, player_id = self.gameplay._seat(connection, data)
        if room is None:
            return {'status': 'error', 'message': '无效的房间或玩家'}
        pending = room.priority_pending
        if room.state == RoomState.GAME_OVER or not pending:
            return {'status': 'error', 'message': '没有待处理的阶段响应询问'}
        if pending['responder'] != player_id or data.get('token') != pending['token']:
            return {'status': 'error', 'message': '响应窗口已失效或不属于你'}
        if time.time() * 1000 >= pending['deadline']:
            await self._pass(room)
            return {'status': 'error', 'message': '阶段响应已超时'}
        if not data.get('respond'):
            await self._pass(room)
            return {'status': 'success'}
        raw = data.get('card')
        card = raw if isinstance(raw, dict) else {}
        # 只能选择此时点公开给响应者的牌；卡表、手牌与目标仍由正式出牌入口复检。
        if not any(c['name'] == card.get('name') for c in pending['speed3_cards']):
            return {'status': 'error', 'message': '请选择本次询问中的可用速阶三卡牌'}
        room.priority_pending = None
        room.priority_continue = {**pending, 'ready': False}
        try:
            ack = await self.gameplay.magic.use_magic_card(connection, {
                'room_id': room.id, 'player_id': player_id, 'card': raw,
                'targets': data.get('targets', {}),
            })
        except Exception:
            room.priority_continue = None
            room.priority_pending = pending
            if time.time() * 1000 >= pending['deadline']:
                await self._pass(room)
            raise
        if ack.get('status') != 'success':
            room.priority_continue = None
            room.priority_pending = pending
            if time.time() * 1000 >= pending['deadline']:
                await self._pass(room)
            return ack
        await self._end_window(room, pending)
        # 连锁同步结算时 hook 已续做；异步连锁则由统一结算出口调用。
        if room.priority_continue and not (room.chain or room.chain_waiting or room.chain_resolving):
            await self.continue_after_chain(room, room.priority_continue)
        return ack

    async def continue_after_chain(self, room: Room, continuation: dict):
        room.priority_continue = {**continuation, 'ready': True}
        await self._resume(room)
        if room.priority_continue and room.id not in self._resuming:
            self._resuming.add(room.id)
            self.gameplay.magic.timers.spawn(room.id, self._wait_obligations(room))

    async def _wait_obligations(self, room: Room):
        try:
            while self.rooms.get_room(room.id) is room and room.priority_continue:
                await asyncio.sleep(0.1)
                async with room_action(room):
                    await self._resume(room)
        finally:
            self._resuming.discard(room.id)

    async def _resume(self, room: Room):
        cont = room.priority_continue
        if not cont or not cont.get('ready'):
            return
        if room.state == RoomState.GAME_OVER or room.current_attacker != cont['actor'] or room.round != cont['round']:
            room.priority_continue = None
            return
        if cont['actor'].startswith('ai-') and self.gameplay.magic.chain_animation_pending(room):
            return
        if room.state != RoomState.ATTACKING or room.disconnected or room.chain or room.chain_waiting or room.chain_resolving or pending_action_reason(room, cont['actor']):
            return
        # 卡牌已改变阶段或回合时，旧转换不能覆盖它的结果。
        room.priority_continue = None
        if getattr(room.current_phase, 'value', room.current_phase) != cont['phase']:
            return
        actor = cont['actor']
        player = room.players.get(actor)
        if player is None:
            return
        method = self.gameplay.enter_battle_phase if cont['action'] == 'enter_battle' else self.gameplay.enter_end_phase
        await method(Connection(sid=player.socket_id or actor, user_id=player.user_id),
                     {'room_id': room.id, 'player_id': actor}, _priority_confirmed=True)
