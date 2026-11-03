"""离线质量门槛，调用真实用例与 master 决策；不复制伤害/胜负规则。

随机策略随机选择合法炮击、阶段动作与可生成目标的牌；目标和后续选项复用
master 的合法解析器（包含启发式，属于偏强的随机基线）。超时/卡住不算失败局，
整批质量校验不通过。仅由离线命令串行调用，不在HTTP工作进程使用全局播种。
"""
from __future__ import annotations
import asyncio
import random

from ..domain import battle as rules
from ..domain.ai import master
from ..domain.magic.rules import can_play_magic_card
from ..domain.daily_challenge import restore_snapshot, snapshot_hash
from ..domain.room.models import RoomState
from .rooms import RoomService, Connection
from .gameplay import GameplayService
from .battle import BattleService
from .magic import MagicService
from .ai import AiService


async def run_trial(snapshot: dict, seed: int, *, actions: list | None = None, policy='random', max_actions=1500) -> dict:
    saved = random.getstate()
    random.seed(seed)
    rng = random
    room = restore_snapshot(snapshot, room_id='offline', user_id='human', name='候选玩家', sid='offline-human')
    rooms = RoomService(turn_timeout_seconds=0)
    rooms.rooms[room.id] = room
    gameplay = GameplayService(rooms, turn_timeout_seconds=0, ai_delay_seconds=0, rng=rng)
    battle = BattleService(rooms, touch_turn=gameplay.touch_turn, rng=rng)
    magic = MagicService(rooms, rng=rng, touch_turn=gameplay.touch_turn, chain_entry_delay_seconds=0,
                         chain_display_delay_seconds=0, chain_response_seconds=0, ai_chain_delay_seconds=0)
    ai = AiService(rooms, gameplay, battle, magic, rng=rng, pacing_seconds=0, settle_poll_seconds=.001,
                   retry_pause_seconds=.001, timers=magic.timers)
    gameplay.magic, gameplay.fire_hook, gameplay.draw_hook = magic, battle.fire, magic.draw
    gameplay.turn_start_hook = lambda r, _p: magic.settle_wuyou_dream(r)
    gameplay.draw_skip_hook, gameplay.after_draw_hook = magic.consume_bingliang_skip, lambda r, _p: magic.settle_bingliang(r)
    gameplay.round_end_hook = magic.on_new_big_round
    magic.ai_place_hook, magic.finish_hook = gameplay.ai_place_board_now, battle.finish_game
    battle.state_sync_hook = magic._sync_each_seat
    battle.sink_hooks.append(magic.on_ship_sunk)
    battle.damage_hooks.append(magic.on_damage)
    battle.attacks_exhausted_hooks.append(magic.on_attacks_exhausted)
    # 外层逐回合驱动同一个master执行器，避免背景任务与种子调度交错。
    async def no_background(*_): return False
    gameplay.ai_turn_hook = no_background
    trace = []
    conn = Connection('offline-human', 'human', '候选玩家')
    methods = {'attack': battle.attack, 'use_magic_card': magic.use_magic_card,
               'enter_battle_phase': gameplay.enter_battle_phase, 'enter_end_phase': gameplay.enter_end_phase,
               'end_turn': gameplay.end_turn}
    last_turn = None
    cast_count = 0

    async def execute(action):
        ack = await methods[action['method']](conn, {'room_id':room.id,'player_id':'human', **action['payload']})
        if ack.get('status') != 'success' and not ack.get('waiting_priority'):
            return False
        trace.append(action)
        return True

    async def play():
        nonlocal cast_count, last_turn
        for _ in range(max_actions):
            await asyncio.sleep(0)
            if room.state == RoomState.GAME_OVER:
                return {'terminal':True, 'won':room.winner == 'human', 'seed':seed, 'actions':trace}
            if room.priority_pending:
                responder = room.priority_pending.get('responder')
                if responder:
                    await gameplay.priority.decline(room, responder)
            for pid in list(room.players):
                await ai.consume_pending(room, pid)
            if room.chain_waiting and room.chain_window == 'human':
                await magic.chain_response(conn, {'room_id':room.id,'player_id':'human','chain':False})
            if room.chain or room.chain_waiting or room.chain_resolving or room.priority_pending:
                await asyncio.sleep(.001)
                continue
            if room.state == RoomState.ROCK_PAPER_SCISSORS:
                for pid, p in room.players.items():
                    if pid not in room.rps_choices:
                        await gameplay.rps_choice(Connection(p.socket_id, p.user_id, p.name),
                            {'room_id':room.id,'player_id':pid,'choice':rng.choice(['rock','paper','scissors'])})
                continue
            if room.state != RoomState.ATTACKING:
                await asyncio.sleep(.001)
                continue
            if room.current_attacker != 'human':
                await ai.run_seat_turn(room, room.current_attacker)
                continue
            turn = (room.round, tuple(room.attack_order), room.current_attacker)
            if turn != last_turn:
                cast_count, last_turn = 0, turn
            if actions is not None:
                if len(trace) >= len(actions) or not await execute(actions[len(trace)]):
                    return {'terminal':False,'won':False,'reason':'胜利轨迹未完成或动作被拒','actions':trace}
                continue
            possible = []
            hand = room.players['human'].magic_hand
            if policy == 'search':
                index, targets = ai.master_pick(room,'human',cast_count)
                if index is not None:
                    possible.append({'method':'use_magic_card','payload':{'card':hand[index].to_payload(),'targets':targets}})
            else:
                for card in hand:
                    if can_play_magic_card(room,'human',card):
                        targets = master.card_readiness(room,'human',card)
                        if targets is not None:
                            possible.append({'method':'use_magic_card','payload':{'card':card.to_payload(),'targets':targets}})
            phase = room.current_phase.value
            if phase == 'battle':
                cells = [(x,y) for y in range(6) for x in range(6) if rules.attack_error(room,'human',x,y) is None]
                if policy == 'search' and cells:
                    target = master.choose_attack(room,'human',rng)
                    cells = [target] if target in cells else cells[:1]
                possible.extend({'method':'attack','payload':{'x':x,'y':y}} for x,y in cells)
                if not cells:
                    possible.append({'method':'enter_end_phase','payload':{}})
            elif phase == 'preparation':
                possible.append({'method':'enter_battle_phase','payload':{}})
            elif phase == 'end':
                possible.append({'method':'end_turn','payload':{}})
            if not possible:
                return {'terminal':False,'won':False,'reason':'没有可生成的合法动作'}
            action = possible[0] if policy == 'search' else rng.choice(possible)
            if await execute(action):
                if action['method'] == 'use_magic_card': cast_count += 1
            else:
                return {'terminal':False,'won':False,'reason':'策略动作被真实规则拒绝','actions':trace}
        return {'terminal':False,'won':False,'reason':'行动数超过上限','actions':trace}

    try:
        return await asyncio.wait_for(play(), timeout=30)
    except TimeoutError:
        return {'terminal':False,'won':False,'reason':'模拟超时'}
    finally:
        rooms._drop_room(room.id)
        for task in list(rooms._tasks): task.cancel()
        random.setstate(saved)


async def qualify(snapshot: dict, *, search_seeds=20, random_trials=50) -> dict:
    if random_trials < 50:
        raise ValueError('随机合法模拟至少50局')
    proof = None
    for seed in range(search_seeds):
        trial = await run_trial(snapshot, seed, policy='search')
        if trial.get('terminal') and trial.get('won'):
            # 同种子逐动作再跑一遍，不能把策略建议冒充可解证据。
            replay = await run_trial(snapshot, seed, actions=trial['actions'])
            if replay.get('terminal') and replay.get('won'):
                proof = trial
                break
    out = {'snapshot_hash':snapshot_hash(snapshot),'solved':bool(proof),'random_trials':0,
           'random_wins':0,'unresolved':0,'reviewed':False,
           'random_policy':'随机合法动作；牌目标及后续选择使用master合法解析器（偏强基线）'}
    if proof is None:
        return out
    out['winning_path'] = proof
    for seed in range(1000,1000+random_trials):
        trial = await run_trial(snapshot, seed)
        out['random_trials'] += 1
        out['random_wins'] += int(trial.get('won',False))
        out['unresolved'] += int(not trial.get('terminal',False))
    if out['unresolved']:
        out['solved'] = False  # 未完成的模拟绝不能伪装成低胜率。
    return out
