"""顺序结算编排；依赖注入的宿主提供通知、摸牌与开回合能力。"""
from . import draft, effects
from ..room.models import RoomState, rank_payload
from ..ai.difficulty import is_ai_seat
from ..ai.mystery_tech import choose_technology, target_payload


class MysteryTechFlow:
    def __init__(self, gameplay):
        self.host = gameplay

    async def publish(self, room):
        if not room.mystery_tech:
            return
        from .. import replay
        s = draft.state(room)
        history = s.get('history', [])
        count = s.get('recorded_count', 0)
        if len(history) > count:
            # 只在双方锁定之后记所选结果，不记录选项、刷新或目标候选。
            replay.note_action(room, 'mystery_tech', '双方锁定神秘科技',
                               {'selected': history[count:]})
            s['recorded_count'] = len(history)
        now = self.host.clock()
        for pid, player in room.players.items():
            if player.socket_id:
                await self.host._publisher.emit('mystery_tech_state',
                    {'room_id': room.id, **draft.snapshot(room, pid, now=now)}, to=player.socket_id)
        await self.host._publisher.emit('mystery_tech_public',
            {'room_id': room.id, **draft.snapshot(room, now=now)}, room=room.id)
        room_state = getattr(room.state, 'value', room.state)
        if (room.state in (RoomState.MYSTERY_TECH_SELECTION, RoomState.ROCK_PAPER_SCISSORS,
                           RoomState.MYSTERY_TECH_RESOLUTION)
                and s.get('published_room_state') != room_state):
            s['published_room_state'] = room_state
            await self.host._publisher.emit('game_state',
                {'state': room_state, 'round': room.round, **rank_payload(room)}, room=room.id)
        await self.host.rooms.viewing.commit(room, cause='mystery_tech')

    async def begin(self, room):
        started = draft.begin(room, self.host.rng, now=self.host.clock())
        if started:
            if room.is_ai_room:
                for pid in room.players:
                    options = draft.state(room)['offers'][pid]
                    if is_ai_seat(pid) and options:
                        draft.lock(room, pid, choose_technology(options, self.host.rng),
                                   self.host.rng, now=self.host.clock())
                # 在首次出示前补换电脑已取走的同名项，不消耗玩家的刷新机会。
                for pid in room.players:
                    if not is_ai_seat(pid):
                        draft._repair_options(room, pid, self.host.rng)
            await self.publish(room)
        return started

    async def start_resolution(self, room):
        s = draft.state(room)
        if not room.mystery_tech or s.get('stage') != 'locked' or s.get('selection_round') != room.round:
            return False
        s['stage'] = 'resolving'
        s['queue'] = [{'player_id': pid, 'tech_id': s['locked'][pid]} for pid in room.attack_order if s['locked'].get(pid)]
        s['cursor'] = 0
        room.state = RoomState.MYSTERY_TECH_RESOLUTION
        await self.advance(room)
        return True

    async def _sync_effects(self, room):
        effects.maintain_fleet(room)
        magic = self.host.magic
        if magic is not None:
            await magic._emit_ships_updated(room)
            for pid, player in room.players.items():
                await magic._emit_player_ships(room, pid)
                await magic._emit_hand(player)
                if player.socket_id:
                    await self.host._publisher.emit('revealed_positions', {'positions': [
                        {'x': pos.x, 'y': pos.y} for pos in player.revealed_positions]}, to=player.socket_id)
            await magic._sync_each_seat(room)

    async def _defeat(self, room):
        from ..battle import is_zero_ship_defeat
        for loser in room.players:
            if is_zero_ship_defeat(room, loser):
                if self.host.magic is not None:
                    await self.host.magic.finish(room, room.opponent_of(loser), loser, '神秘科技结算后无战舰可用')
                return True
        return False

    async def advance(self, room):
        s = draft.state(room)
        while s['cursor'] < len(s['queue']) and room.state != RoomState.GAME_OVER:
            item = s['queue'][s['cursor']]
            pid, tech_id = item['player_id'], item['tech_id']
            if tech_id in effects.TARGETED:
                request = effects.target_request(room, pid, tech_id, now=self.host.clock())
                if effects.actionable(request):
                    s.update(stage='targeting', target=request)
                    await self._present_target(room, request)
                    return
            else:
                result = effects.apply(room, pid, tech_id, self.host.rng)
                for _ in range(result['draw']):
                    await self.host._draw(room, pid)
                if ship := result.get('sunk_ship'):
                    if self.host.magic is not None:
                        await self.host.magic.on_ship_sunk(room, room.opponent_of(pid), ship, magic=True, attacker_id=pid)
            s['cursor'] += 1
            await self._sync_effects(room)
            if await self._defeat(room):
                break
            if self.host.magic is not None and self.host.magic._chain_interaction_pending(room):
                s.update(stage='effect_waiting', target=None, waiting_player=pid)
                await self.publish(room)
                return
        if room.state == RoomState.GAME_OVER:
            s.update(stage='ended', target=None)
        else:
            s.update(stage='idle', target=None)
            await self.host._complete_rps_turn(room)
        await self.publish(room)

    async def _present_target(self, room, request):
        await self.publish(room)
        pid = request['player_id']
        if room.is_ai_room and is_ai_seat(pid):
            payload = target_payload(request, self.host.rng)
            if payload is not None:
                await self.target(room, pid, payload)
            else:
                s = draft.state(room)
                s.update(stage='resolving', target=None, cursor=s['cursor'] + 1)
                await self.advance(room)

    async def target(self, room, pid, data, *, timed_out=False):
        s = draft.state(room)
        request = s.get('target')
        if (not room.mystery_tech or s.get('stage') != 'targeting' or not request
                or request['player_id'] != pid or data.get('request_id') != request['request_id']):
            return '没有属于你的科技瞄准窗口，或请求已过期'
        if not timed_out and self.host.clock() * 1000 >= request['deadline']:
            return '科技瞄准已超时'
        if error := effects.answer(room, request, data):
            return error
        await self._sync_effects(room)
        if await self._defeat(room):
            s.update(stage='ended', target=None)
            await self.publish(room)
            return None
        remaining = request['remaining'] - 1
        if remaining > 0:
            next_request = effects.target_request(room, pid, request['tech_id'], now=self.host.clock(), remaining=remaining)
            next_request['deadline'] = request['deadline']
            if effects.actionable(next_request):
                s['target'] = next_request
                await self._present_target(room, next_request)
                return None
        s.update(stage='resolving', target=None, cursor=s['cursor'] + 1)
        if self.host.magic is not None and self.host.magic._chain_interaction_pending(room):
            s.update(stage='effect_waiting', waiting_player=pid)
            await self.publish(room)
            return None
        await self.advance(room)
        return None

    async def sweep(self, room, now):
        if not room.mystery_tech or room.state == RoomState.GAME_OVER:
            return False
        if draft.expire(room, self.host.rng, now=now):
            await self.publish(room)
            return True
        s = draft.state(room)
        if s.get('stage') == 'effect_waiting':
            magic = self.host.magic
            acted = False
            if magic is not None and magic._chain_interaction_pending(room):
                acted = await magic.settle_interaction_timeout(room, now, self.host.turn_timeout_seconds)
            if room.state == RoomState.GAME_OVER:
                return True
            if magic is not None and not magic._chain_interaction_pending(room):
                s.update(stage='resolving', waiting_player=None)
                if not await self._defeat(room):
                    await self.advance(room)
                return True
            return acted
        request = s.get('target')
        if s.get('stage') != 'targeting' or not request or now * 1000 < request['deadline']:
            return False
        # 舰队重生的专门默认：15秒超时即停止；其余义务随机补齐。
        if request['tech_id'] == 'fleet_rebirth':
            s.update(stage='resolving', target=None, cursor=s['cursor'] + 1)
            await self.advance(room)
            return True
        while s.get('target') and s['target']['deadline'] <= now * 1000:
            request = s['target']
            payload = {'request_id': request['request_id']}
            if request['ship_indices']:
                payload['ship_index'] = self.host.rng.choice(request['ship_indices'])
            if request['legal_cells']:
                payload.update(self.host.rng.choice(request['legal_cells']))
            error = await self.target(room, request['player_id'], payload, timed_out=True)
            if error:
                # 目标失效或无法放下整船时结束本项，不能让看门狗无限循环。
                s.update(stage='resolving', target=None, cursor=s['cursor'] + 1)
                await self.advance(room)
                break
        return True
