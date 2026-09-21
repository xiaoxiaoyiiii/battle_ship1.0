# -*- coding: utf-8 -*-
"""复现：大师 AI 当施法者时，重摆类卡把**对手（真人）**拖进布船屏。

────────────────────────────────────────────────────────────────────────
用户原话
────────────────────────────────────────────────────────────────────────
    「大师AI出牌有很大问题 太快了实在是 而且是在代码底层里直接出牌
      我刚刚验收的对局中它突然使用了回光返照加灵气复苏
      直接把我需要重新摆船的界面卡没了 我自己棋盘上甚至一个船都没有了」

────────────────────────────────────────────────────────────────────────
复现到的是**哪一层**
────────────────────────────────────────────────────────────────────────
服务端 handler 层（无头）。真人那一侧的**界面**用三项可观察事实代替：

  · 真人的 socket（`sid`）在整段里有没有收到 `reset_gameboard`；
  · `room.state` 有没有停在 `placing_ships`；
  · 真人那一侧棋盘的服务端真相（`human.ships` / `human.max_ships`）。

这三项就是前端 `reset_gameboard` / `game_state(state='placing_ships')`
两条入口的全部输入 —— 收不到事件、或 state 停在 placing_ships 而没收到事件，
真人的界面就不可能被正确地切进"可以重新摆船"的状态（见 static/game.js:6135
与 static/game.js:1437）。**浏览器里的像素没有跑**，见报告里的"未验证"一节。

────────────────────────────────────────────────────────────────────────
两张卡怎么凑到一起（这就是用户看到的那一串）
────────────────────────────────────────────────────────────────────────
① `回光返照`（server.py 回光返照分支）：
     caster.ships = []                    # 只清施法者自己
     room.state = 'placing_ships'
     room.huiguang_awaiting_placement = True
     emit('reset_gameboard', …, to=caster.sid)     # 只发给施法者
   AI 当施法者时 `caster.sid == 'ai-<room_id>'` —— **没有这条 socket**，
   事件石沉大海。而 `room.state` 已经是 placing_ships。

② AI 循环里"自己爬起来"的那段是**异步**的（`_ai_turn_loop` 后台任务里
   `if room.state == 'placing_ships': _ai_place_board(...)`，server.py:6262）。
   它要等这一圈循环转回来才发生 —— 于是「①之后、②之前」有一段窗口，
   房间停在 placing_ships，而真人什么事件都没收到。

③ 在这段窗口里 AI 继续出牌（`_ai_master_turn` 每回合可以连打
   `ai_brain.CARDS_PER_TURN` 张）：`灵气复苏` 会把**双方**棋盘清空、
   把 `room.state` 又写一次 placing_ships，然后给双方各发一份 reset_gameboard。

④ 关键：`_ai_master_turn` 的"自己爬起来"判据是
   `if room.state == 'placing_ships':` —— ③ 之后它仍然是 placing_ships，
   所以还会去摆。但此时 `灵気复苏` 把 `room.magic_temp_data = {}` **整体覆写**了
   （CLAUDE.md 教训 #30），而 `huiguang_awaiting_placement` 是**房间级**字段、
   没人清 —— 收尾判据就此错位。

本脚本把 ①→②③ 的窗口原样摆出来，然后问三个问题：
   Q1 真人有没有收到 reset_gameboard？
   Q2 房间有没有停在 placing_ships？
   Q3 真人此时点"确认布船"能不能成功（前端就是这条 ack）？

用法：
    python tools/repro_ai_huiguang_placement.py
退出码 1 = 复现到了（有缺陷）；0 = 没复现到。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server
from server import Player, PlayerShip, Position   # noqa: F401


EVENTS = []


def _install_headless_socket():
    """把 socket 出口换成记录器（无头环境没有真连接，也不许起后台任务）。"""
    def fake_emit(event, data, to=None, room=None):
        EVENTS.append((event, data, to, room))

    server.emit = fake_emit
    server.socketio.start_background_task = lambda *a, **k: None
    server.socketio.emit = lambda *a, **k: None
    server._maybe_run_ai_turn = lambda *a, **k: None


def build_room():
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

    room.state = 'attacking'
    room.current_attacker = ai_id
    room.current_phase = 'battle'
    room.attack_order = [ai_id, 'human-0']
    room.round = 3
    room.attacks_remaining = 6
    # 手牌：AI 只需要这两张（顺序就是用户看到的那一串）
    room.players[ai_id].magic_hand = [server.MagicCard('回光返照'),
                                      server.MagicCard('灵气复苏')]
    return room, ai_id


def use_card(room, pid, name, targets=None):
    card = server.MagicCard(name)
    return server.handle_use_magic_card({
        'room_id': room.id, 'player_id': pid,
        'card': {'name': card.name, 'speed': card.speed, 'type': card.type,
                 'description': getattr(card, 'description', '')},
        'targets': targets or {},
    })


def dump(room, ai_id, title):
    human = room.players['human-0']
    ai = room.players[ai_id]
    print(f'\n── {title} ──')
    print(f'  room.state                 = {room.state}')
    print(f'  room.current_attacker      = {room.current_attacker}')
    print(f'  ai.ships / max_ships       = {len(ai.ships)} / {ai.max_ships!r}')
    print(f'  human.ships / max_ships    = {len(human.ships)} / {human.max_ships!r}')
    print(f'  huiguang_awaiting_placement= '
          f'{getattr(room, "huiguang_awaiting_placement", None)}')
    print(f'  lingqi_resurgence_applied  = '
          f'{getattr(room, "lingqi_resurgence_applied", None)}')
    print(f'  magic_temp_data            = {room.magic_temp_data!r}')


def main():
    _install_headless_socket()
    room, ai_id = build_room()

    print('=' * 74)
    print('复现：大师 AI 打出「回光返照」+「灵气复苏」')
    print('=' * 74)
    print(f'  room_id = {room.id}')
    print(f'  ai_id   = {ai_id!r}  （注意：这是**没有任何 socket 连接**的假座位）')

    # ── ① AI 打出回光返照（走真实 handler，与线上同一条路） ────────────
    r1 = use_card(room, ai_id, '回光返照')
    print(f'\n[① 回光返照] status={r1.get("status")} msg={r1.get("message")}')
    reset_1 = [to for (ev, _d, to, _r) in EVENTS if ev == 'reset_gameboard']
    print(f'    reset_gameboard 收件人 = {reset_1}')
    dump(room, ai_id, '① 之后（AI 还没"爬起来"的那段窗口）')

    q1_ai_sid_got_it = ai_id in reset_1
    q1_human_got_it = 'human-0' in reset_1
    q2_stuck = room.state == 'placing_ships'

    # ── ② 还没等 AI 爬起来，AI 又打出灵气复苏（同一回合连打） ──────────
    #    灵气复苏会开 `lingqi_choice` 挑船数，AI 走 `_ai_consume_own_choice`
    #    消费它（server.py:10088 一带）。这里照线上那条通道原样走一遍。
    r2 = use_card(room, ai_id, '灵气复苏')
    print(f'\n[② 灵气复苏] status={r2.get("status")} msg={r2.get("message")}')
    room = server.room_manager.get_room(room.id)
    print(f'    挑船数待办 = {(room.magic_temp_data or {}).get("type")!r}')
    server._ai_consume_own_choice(room, ai_id)
    room = server.room_manager.get_room(room.id)
    reset_2 = [to for (ev, _d, to, _r) in EVENTS if ev == 'reset_gameboard']
    print(f'    reset_gameboard 收件人（累计） = {reset_2}')
    dump(room, ai_id, '② 之后')

    human2_got_it = 'human-0' in reset_2

    # ── ③ 走 AI 循环那两处"自己爬起来"（server.py:6262 / 6340） ────────
    print('\n[③ 走 _ai_master_turn 里那两段自救代码]')
    if room.state == 'placing_ships':
        server._ai_place_board(room, ai_id)
        other = server._opponent_of(room, ai_id)
        print(f'    _ai_place_board(ai) 之后 state = {room.state}')
        if other and room.state == 'placing_ships':
            # 对方的棋盘它也会替人摆 —— 但**真人那边界面永远不知道**
            server._ai_place_board(room, other)
            print(f'    _ai_place_board(human) 之后 state = {room.state} '
                  f'（注意：真人对此毫不知情）')
    room = server.room_manager.get_room(room.id)
    dump(room, ai_id, '③ 自救之后')

    # ── ④ 真人此刻的真实体验：他收到的最后一条"房间状态"是什么？ ───────
    print('\n[④ 真人侧可观察事实]')
    human_resets = [d for (ev, d, to, _r) in EVENTS
                    if ev == 'reset_gameboard' and to == 'human-0']
    print(f'    真人收到的 reset_gameboard 份数 = {len(human_resets)}')
    for d in human_resets:
        print(f'      · new_max_ships={d.get("new_max_ships")!r} msg={d.get("message")!r}')
    print(f'    回光返照发出去的那一份收件人是 AI 假座位：{q1_ai_sid_got_it}')
    print(f'    回光返照那一份真人收到了吗：{q1_human_got_it}')
    print(f'    ① 之后房间停在 placing_ships：{q2_stuck}')
    print(f'    灵气复苏那一份真人收到了吗：{human2_got_it}')

    # ── 结论 ──────────────────────────────────────────────────────────
    print('\n' + '=' * 74)
    reproduced = q1_ai_sid_got_it and not q1_human_got_it and q2_stuck
    server.room_manager.delete_room(room.id)
    if reproduced:
        print('复现成功（这是**修之前**的症状）：')
        print('  回光返照把房间推进 placing_ships，事件却发给了 AI 的假 sid，')
        print('  真人一份都没收到 —— 他那一侧「要重新摆船却无从下手」。')
        print('=' * 74)
        return 1
    print('已修复（这是**修之后**的结果）：')
    print('  ① 之后房间没有停在 placing_ships —— AI 施法者已经**就地摆完**，')
    print('     真人一份 reset_gameboard 都不需要收到（他棋盘本来就没被动过）。')
    print('=' * 74)
    return 0


if __name__ == '__main__':
    sys.exit(main())
