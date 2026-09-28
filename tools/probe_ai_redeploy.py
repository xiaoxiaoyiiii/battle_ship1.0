# -*- coding: utf-8 -*-
"""复现探针：大师 AI 当施法者时的「重摆类卡」两连打（无头，服务端 handler 层）。

对每一张会要求重新摆放的卡组合，按 `_ai_master_turn` 的真实调用顺序走一遍：

    出牌① → 出牌② → （`_ai_master_turn` 里那两段"自己爬起来"）

然后打印**真人侧**的可观察事实：`room.state`、真人收到的
`reset_gameboard` 份数、双方棋盘与服务端真相。

用法：
    python tools/probe_ai_redeploy.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server
from server import Player, PlayerShip, Position


EVENTS = []


def install():
    def fake_emit(event, data, to=None, room=None):
        EVENTS.append((event, data, to, room))

    server.emit = fake_emit
    server.socketio.start_background_task = lambda *a, **k: None
    server.socketio.emit = lambda *a, **k: None
    server._maybe_run_ai_turn = lambda *a, **k: None
    server._schedule_chain_timeout = lambda *a, **k: None


def build_room(hand):
    room_id = server.room_manager.create_ai_room('human-0', 'P2', None, 'master')
    room = server.room_manager.get_room(room_id)
    room.players['human-0'] = Player(
        name='P2', ships=[], attacks=[], remaining_ships=0,
        user_id=None, sid='human-0')
    room.init_player_magic('human-0', server.magic_cards)
    ai_id = server._ai_player_id(room)
    for pid in room.players:
        p = room.players[pid]
        p.ships = [PlayerShip(positions=[Position(x=i, y=0)], hits=[]) for i in range(6)]
        p.remaining_ships = 6
        p.max_ships = 6
        p.attacks = []
        p.revealed_positions = []
        p.magic_hand = []
    room.state = 'attacking'
    room.current_attacker = ai_id
    room.current_phase = 'battle'
    room.attack_order = [ai_id, 'human-0']
    room.round = 3
    room.attacks_remaining = 6
    room.magic_deck = [server.MagicCard(n) for n in
                       ['冻结', '轰炸', '增援', '疗愈', '看破！', '无中生有']]
    room.players[ai_id].magic_hand = [server.MagicCard(n) for n in hand]
    return room, ai_id


def use(room, pid, name):
    card = server.MagicCard(name)
    return server.handle_use_magic_card({
        'room_id': room.id, 'player_id': pid,
        'card': {'name': card.name, 'speed': card.speed, 'type': card.type,
                 'description': getattr(card, 'description', '')},
        'targets': {},
    })


def facts(room, ai_id, tag):
    human = room.players['human-0']
    ai = room.players[ai_id]
    got = [d for (ev, d, to, _r) in EVENTS
           if ev == 'reset_gameboard' and to == 'human-0']
    print(f'  {tag:<26} state={room.state:<15} ai={len(ai.ships)}/{ai.max_ships!r} '
          f'human={len(human.ships)}/{human.max_ships!r} '
          f'huiguang={getattr(room, "huiguang_awaiting_placement", None)} '
          f'lingqi={getattr(room, "lingqi_resurgence_applied", None)} '
          f'human_resets={len(got)}')


def scenario(hand):
    EVENTS.clear()
    room, ai_id = build_room(hand)
    print(f'\n=== 手牌 {hand} ===')
    facts(room, ai_id, '起手')
    for name in hand:
        resp = use(room, ai_id, name)
        room = server.room_manager.get_room(room.id)
        print(f'  use {name}: {resp.get("status")} / {resp.get("message")}')
        if resp.get('status') == 'success':
            server._ai_consume_own_pending(room.id, ai_id)
            room = server.room_manager.get_room(room.id)
        facts(room, ai_id, f'出牌后({name})')

    # `_ai_master_turn` 的自救（server.py:6262 一带）
    room = server.room_manager.get_room(room.id)
    if room.state == 'placing_ships':
        server._ai_place_board(room, ai_id)
        other = server._opponent_of(room, ai_id)
        if other and room.state == 'placing_ships':
            server._ai_place_board(room, other)
        room = server.room_manager.get_room(room.id)
        facts(room, ai_id, 'AI 自救之后')
    else:
        print('  （房间没停在 placing_ships，AI 自救那段不会跑）')

    # 真人此刻的真实处境
    human = room.players['human-0']
    got = [d for (ev, d, to, _r) in EVENTS
           if ev == 'reset_gameboard' and to == 'human-0']
    print(f'  → 真人收到 reset_gameboard：{len(got)} 份；'
          f'room.state={room.state}；真人服务端棋盘={len(human.ships)} 艘')
    server.room_manager.delete_room(room.id)


def human_side(hand):
    """把真人那一侧**照他的真实处境**走完：他只知道自己该重新摆船。"""
    EVENTS.clear()
    room, ai_id = build_room(hand)
    print(f'\n=== 真人侧全流程：AI 手牌 {hand} ===')
    for name in hand:
        use(room, ai_id, name)
        room = server.room_manager.get_room(room.id)
        if room.state == 'placing_ships' or room.chain:
            server._ai_consume_own_pending(room.id, ai_id)
            room = server.room_manager.get_room(room.id)

    # AI 自救
    room = server.room_manager.get_room(room.id)
    if room.state == 'placing_ships':
        server._ai_place_board(room, ai_id)
        other = server._opponent_of(room, ai_id)
        if other and room.state == 'placing_ships':
            server._ai_place_board(room, other)
        room = server.room_manager.get_room(room.id)

    human = room.players['human-0']
    got = [d for (ev, d, to, _r) in EVENTS
           if ev == 'reset_gameboard' and to == 'human-0']
    print(f'  真人收到 reset_gameboard {len(got)} 份 → '
          f'前端 gameState.maxShips = {got[-1]["new_max_ships"] if got else "（没收到，保持旧值）"}')
    print(f'  服务端此刻：state={room.state} human.ships={len(human.ships)} '
          f'max_ships={human.max_ships!r} current_attacker={room.current_attacker}')

    # 真人在**服务端已经替他摆好**的情况下，按下"确认布船"
    # （前端 `confirmShipsBtn` → `place_ships`；他只会按 max_ships 摆）
    n = int(human.max_ships or 6)
    ships = [{'positions': [{'x': i, 'y': 2}], 'hits': []} for i in range(n)]
    resp = server.handle_place_ships({'room_id': room.id, 'player_id': 'human-0',
                                      'ships': ships})
    print(f'  真人点「确认布船」({n} 艘) → {resp}')
    room = server.room_manager.get_room(room.id)
    human = room.players['human-0']
    print(f'  之后：state={room.state} human.ships={len(human.ships)} '
          f'current_attacker={room.current_attacker} phase={room.current_phase} '
          f'attacks_remaining={room.attacks_remaining}')
    print(f'        huiguang={getattr(room, "huiguang_awaiting_placement", None)} '
          f'lingqi={getattr(room, "lingqi_resurgence_applied", None)} '
          f'zero_attacks_for={room.game_effects.get("zero_attacks_for")}')
    server.room_manager.delete_room(room.id)


    # 闸门验证放在 `gate_check()` 里（见下）。


def gate_check():
    print('\n=== 闸门验证：重摆窗口内不许再选出一张重摆卡 ===')
    EVENTS.clear()
    room, ai_id = build_room(['回光返照', '灵气复苏'])
    use(room, ai_id, '灵气复苏')
    room = server.room_manager.get_room(room.id)
    server._ai_consume_own_pending(room.id, ai_id)
    room = server.room_manager.get_room(room.id)
    facts(room, ai_id, '灵气复苏结算完（AI 已摆）')
    idx, targets = server._ai_choose_card(room, ai_id, 0)
    print(f'  _ai_choose_card → idx={idx!r} targets={targets!r} '
          f'（手牌={[c.name for c in room.players[ai_id].magic_hand]}）')
    readiness = server._master_card_readiness(room, ai_id,
                                             server.MagicCard('回光返照'))
    print(f'  _master_card_readiness(回光返照) = {readiness!r}')
    print(f'  → 闸门生效：{idx is None and readiness is None}')
    server.room_manager.delete_room(room.id)


def main():
    install()
    for hand in (['回光返照'], ['灵气复苏'], ['败者食尘'],
                 ['回光返照', '灵气复苏'], ['灵气复苏', '回光返照']):
        scenario(hand)
    for hand in (['回光返照'], ['灵气复苏', '回光返照']):
        human_side(hand)
    gate_check()


if __name__ == '__main__':
    main()
