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
from ..domain.magic.precheck import precheck
from ..domain.room import alive_ships
from ..domain.room.models import field_magic_name
from ..domain import placement as placement_rules
from ..domain.daily_challenge import restore_snapshot, snapshot_hash
from ..domain.room.models import RoomState
from .rooms import RoomService, Connection
from .gameplay import GameplayService
from .battle import BattleService
from .magic import MagicService
from .ai import AiService


class _HeadlessMagic(MagicService):
    @staticmethod
    def _mark_dice_animation(room, payload):
        # 骰子结果已经由生产效果结算；离线没有覆盖层，只省去客户端展示等待。
        # 选牌、选船、连锁和重摆待办仍由原用例处理，不能直接清除。
        pass


async def run_trial(snapshot: dict | None, seed: int, *, actions: list | None = None, policy='random', max_actions=1500) -> dict:
    saved = random.getstate()
    random.seed(seed)
    rng = random
    rooms = RoomService(turn_timeout_seconds=0)
    conn = Connection('offline-human', 'human', '模拟舰长')
    source = None
    if snapshot is None:
        created = await rooms.create_ai_room(conn, {'difficulty': 'master'})
        room = rooms.get_room(created['room_id'])
        from ..domain import mutations
        mutations.configure_room(room, 'custom', ids=[], rng=rng)
        await rooms.join_room(conn, {'room_id': room.id})
        source = {'simulated': True, 'seed': seed, 'ai_difficulty': 'master', 'human_policy': policy,
                  'initial_deck': [card.name for card in room.magic_deck]}
    else:
        room = restore_snapshot(snapshot, room_id='offline', user_id='human', name='候选玩家', sid=conn.sid)
        rooms.rooms[room.id] = room
    gameplay = GameplayService(rooms, turn_timeout_seconds=0, ai_delay_seconds=0, rng=rng)
    gameplay.priority.seconds = 0
    battle = BattleService(rooms, touch_turn=gameplay.touch_turn, rng=rng)
    magic = _HeadlessMagic(rooms, rng=rng, touch_turn=gameplay.touch_turn, chain_entry_delay_seconds=0,
                         chain_display_delay_seconds=0, chain_response_seconds=10, ai_chain_delay_seconds=0)
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
    if source is not None:
        cells = rng.sample([(x,y) for y in range(6) for x in range(6)], 6)
        ack = await gameplay.place_ships(conn, {'room_id':room.id, 'player_id':'human',
            'ships':[{'positions':[{'x':x,'y':y}]} for x,y in cells]})
        if ack.get('status') != 'success':
            raise ValueError(f'模拟源布船失败:{ack}')
        source['opening_ships'] = {pid: [[{'x':p.x,'y':p.y} for p in ship.positions]
                                         for ship in player.ships] for pid,player in room.players.items()}
    trace = []
    methods = {'attack': battle.attack, 'use_magic_card': magic.use_magic_card,
               'papal_discard': magic.papal_discard,
               'enter_battle_phase': gameplay.enter_battle_phase, 'enter_end_phase': gameplay.enter_end_phase,
               'end_turn': gameplay.end_turn}
    last_turn = None
    cast_count = 0
    rejected = {}

    def diagnostic():
        return {'state':room.state.value,'phase':room.current_phase.value,'round':room.round,
                'attacker':room.current_attacker,'attacks':room.attacks_remaining,
                'ships':{pid:p.remaining_ships for pid,p in room.players.items()},
                'chain_window':room.chain_window,'chain_waiting':room.chain_waiting,
                'priority':room.priority_pending,'magic_temp':room.magic_temp_data,
                'trace_length':len(trace),'recent_logs':room.game_logs[-3:]}

    response_lock = asyncio.Lock()

    async def answer_human():
        async with response_lock:
            await ai.consume_pending(room, 'human')
            if room.pending_dice_discard.get('human') is False:
                hand = room.players['human'].magic_hand
                await magic.dice_discard_choose(conn, {'room_id':room.id,'player_id':'human',
                    'card_index':rng.randrange(len(hand)) if hand else 0})

    async def respond():
        # 对手执行器等待期间，模拟真人客户端仍须独立回答自己的选牌/数字/重摆。
        # 只用正常用例确认；连锁明确选择不反制，不直接清除任何业务待办。
        while room.state != RoomState.GAME_OVER:
            await answer_human()
            player = room.players['human']
            if room.state == RoomState.PLACING_SHIPS and player.needs_reset:
                allowed = (room.game_effects.get('reset_allowed_cells') or {}).get('human')
                cells = [(int(p['x']),int(p['y'])) for p in allowed] if allowed is not None else [(x,y) for y in range(6) for x in range(6)]
                count = placement_rules.expected_ship_count(player)
                if len(cells) >= count > 0:
                    selected = rng.sample(cells,count)
                    await gameplay.place_ships(conn, {'room_id':room.id,'player_id':'human',
                        'ships':[{'positions':[{'x':x,'y':y}]} for x,y in selected]})
            if room.priority_pending and room.priority_pending.get('responder') == 'human':
                await gameplay.priority.decline(room, 'human')
            if room.chain_waiting and room.chain_window == 'human':
                await magic.chain_response(conn, {'room_id':room.id,'player_id':'human','chain':False})
            await asyncio.sleep(.001)

    responder = asyncio.create_task(respond())

    async def execute(action):
        if action.get('rng_state'):
            def tuples(value): return tuple(tuples(x) for x in value) if isinstance(value,(tuple,list)) else value
            rng.setstate(tuples(action['rng_state']))
        before_rng = rng.getstate()
        ack = await methods[action['method']](conn, {'room_id':room.id,'player_id':'human', **action['payload']})
        if ack.get('status') != 'success' and not ack.get('waiting_priority'):
            rejected.update(action=action, ack=ack)
            return False
        trace.append({**action, **({'rng_state':before_rng} if policy == 'search' else {})})
        return True

    async def play():
        nonlocal cast_count, last_turn
        for _ in range(max_actions):
            await asyncio.sleep(0)
            if responder.done() and room.state != RoomState.GAME_OVER:
                responder.result()
            if room.state == RoomState.GAME_OVER:
                return {'terminal':True, 'won':room.winner == 'human', 'seed':seed, 'actions':trace}
            if room.priority_pending:
                priority_responder = room.priority_pending.get('responder')
                if priority_responder:
                    await gameplay.priority.decline(room, priority_responder)
            for pid in list(room.players):
                if pid == 'human':
                    await answer_human()
                else:
                    await ai.consume_pending(room, pid)
            if room.chain_waiting and room.chain_window == 'human':
                await magic.chain_response(conn, {'room_id':room.id,'player_id':'human','chain':False})
            if room.chain or room.chain_waiting or room.chain_resolving or room.priority_pending or room.pending_dice_discard:
                await asyncio.sleep(.001)
                continue
            await ai._wait_animation(room, room.current_attacker)
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
                last_turn = None
                await ai.run_seat_turn(room, room.current_attacker)
                continue
            turn = (room.round, tuple(room.attack_order), room.current_attacker)
            if turn != last_turn:
                cast_count, last_turn = 0, turn
            if actions is not None:
                if len(trace) >= len(actions) or not await execute(actions[len(trace)]):
                    return {'terminal':False,'won':False,'reason':'胜利轨迹未完成或动作被拒','actions':trace,
                            'diagnostic':diagnostic(), 'rejected':rejected}
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
                        if card.name in ('神之宣告','钢筋铁骨'):
                            count = 2 if card.name == '神之宣告' else 1
                            ships = alive_ships(room.players['human'])
                            if len(ships) >= count:
                                targets = {'board':'self','selected_cells':[{'x':s.positions[0].x,'y':s.positions[0].y}
                                    for s in rng.sample(ships,count)]}
                                if count == 2: targets['effect_choice'] = rng.choice([1,2])
                        if targets is not None and not precheck(room,'human',card.name,targets):
                            possible.append({'method':'use_magic_card','payload':{'card':card.to_payload(),'targets':targets}})
            phase = room.current_phase.value
            if phase == 'battle':
                if field_magic_name(room) == '教皇旨意' and not rules.attacks_forced_zero(room):
                    possible.extend({'method':'papal_discard','payload':{'discard_card_indices':[i]}} for i in range(len(hand)))
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
                return {'terminal':False,'won':False,'reason':'策略动作被真实规则拒绝','actions':trace,
                        'diagnostic':diagnostic(), 'rejected':rejected}
        return {'terminal':False,'won':False,'reason':'行动数超过上限','actions':trace,'diagnostic':diagnostic()}

    try:
        result = await asyncio.wait_for(play(), timeout=30)
        if source is not None:
            from .replays import build_replay
            source['winner'] = 'human' if result.get('won') else 'master' if result.get('terminal') else 'unresolved'
            result.update(source=source, snapshots=room.daily_candidate_snapshots, replay=build_replay(room))
        return result
    except TimeoutError:
        return {'terminal':False,'won':False,'reason':'模拟超时','diagnostic':diagnostic()}
    finally:
        responder.cancel()
        await asyncio.gather(responder, return_exceptions=True)
        rooms._drop_room(room.id)
        for task in list(rooms._tasks): task.cancel()
        await magic.stop()
        random.setstate(saved)


async def qualify(snapshot: dict, *, search_seeds=20, random_trials=50, reject_early=False) -> dict:
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
        if reject_early and (out['unresolved'] or out['random_wins'] / random_trials > .1):
            # 仅提前淘汰已注定不达标的候选；实际次数原样记录，绝不外推成50局。
            out['rejection_reason'] = trial.get('reason', '随机通关数已超过本批10%上限')
            break
    if out['unresolved']:
        out['solved'] = False  # 未完成的模拟绝不能伪装成低胜率。
    return out
