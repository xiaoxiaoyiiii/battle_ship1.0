# -*- coding: utf-8 -*-
"""死角 B 复现脚本：打一次「回光返照」，逐帧打印 `room.state` / `room.current_phase`。

**纯服务端层**（不走前端、不起 socket 客户端）—— 只是把 handler 调一遍，
在每一步前后打印状态，看房间到底落到了哪里。

用法：
    python tools/repro_huiguang_room_state.py            # 两个场景都跑
    python tools/repro_huiguang_room_state.py --label v5 # 只打标签（脚本本身与版本无关）
"""
import argparse
import io
import json
import os
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('BATTLESHIP_DB_PATH', str(ROOT / '.tmp' / 'huiguang_repro.db'))

# 把 stdout 强制成 UTF-8（Windows 控制台默认 GBK，中文直接抛 UnicodeEncodeError）
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                                       # noqa: BLE001
    pass

import server  # noqa: E402
from server import GameRoom, MagicCard, Player, PlayerShip, Position, room_manager  # noqa: E402

SID_A = 'hg-sid-a'          # 施法者（场景 1：真人）
SID_B = 'hg-sid-b'
AI_ID = 'ai-hgroom'         # 场景 2：施法者是 AI


class _Sent:
    """把服务端发出去的事件按顺序记下来（事件名 + 目标 room）。"""

    def __init__(self):
        self.rows = []

    def install(self, monkeypatch_like=True):
        for name in ('emit',):
            pass
        self._real_emit = server.emit
        self._real_sio_emit = server.socketio.emit

        def emit_spy(event, *a, **kw):
            self.rows.append((event, kw.get('room'), kw.get('to')))
            return None

        def sio_spy(event, *a, **kw):
            self.rows.append((event + '(sio)', kw.get('room'), kw.get('to')))
            return None

        server.emit = emit_spy
        server.socketio.emit = sio_spy
        return self

    def uninstall(self):
        server.emit = self._real_emit
        server.socketio.emit = self._real_sio_emit

    def drain(self):
        rows, self.rows = self.rows, []
        return rows


def _ships(row):
    return [PlayerShip(positions=[Position(x, row)], hits=[]) for x in range(6)]


def _make_room(room_id, caster_is_ai):
    room = GameRoom(room_id)
    pid_a = AI_ID if caster_is_ai else SID_A
    room.players[pid_a] = Player(name='甲', ships=_ships(0), attacks=[],
                                 remaining_ships=6, sid=pid_a, user_id=None if caster_is_ai else 1)
    room.players[SID_B] = Player(name='乙', ships=_ships(5), attacks=[],
                                 remaining_ships=6, sid=SID_B, user_id=2)
    room.state = 'attacking'
    room.current_phase = 'preparation'
    room.current_attacker = pid_a
    room.attack_order = [pid_a, SID_B]
    room.attacks_remaining = 6
    room.round = 3
    room.ranked = False
    room.game_logs = []
    room.is_ai_room = bool(caster_is_ai)
    if caster_is_ai:
        room.ai_difficulty = 'easy'
    # 双方都打过炮（回光返照要求"自己先手"）
    room.players[pid_a].attacks.append(Position(x=1, y=5, hit=True, ship_sunk=False))
    room.players[SID_B].attacks.append(Position(x=2, y=0, hit=False, ship_sunk=False))
    room_manager.rooms[room.id] = room
    return room, pid_a


def _snap(room):
    return {
        'state': room.state,
        'current_phase': room.current_phase,
        'current_attacker': room.current_attacker,
        'attacks_remaining': room.attacks_remaining,
        'round': room.round,
        'huiguang_awaiting_placement': getattr(room, 'huiguang_awaiting_placement', None),
        'lingqi_resurgence_applied': getattr(room, 'lingqi_resurgence_applied', None),
        'ships': {k: len(v.ships) for k, v in room.players.items()},
    }


def _line(tag, room, note=''):
    print('  %-26s %s%s' % (tag, json.dumps(_snap(room), ensure_ascii=False, sort_keys=True),
                            ('   # ' + note) if note else ''))


def scenario(caster_is_ai):
    who = 'AI 座位施法' if caster_is_ai else '真人施法'
    print('=' * 100)
    print('场景：%s' % who)
    print('=' * 100)
    room, pid = _make_room('hg-repro-%s' % ('ai' if caster_is_ai else 'human'), caster_is_ai)
    sent = _Sent().install()
    try:
        _line('初始', room, '先手 = 施法者')

        print('  --- ① 打出「回光返照」（apply_magic_effect）---')
        res = server.apply_magic_effect(room, pid, MagicCard('回光返照'), {})
        _line('apply_magic_effect 之后', room, str(getattr(res, 'message', res)))
        print('     发出的事件：%s' % [r[0] for r in sent.drain()])

        print('  --- ② reset_gameboard（服务端给双方下发的"清棋盘"单发事件）---')
        # 这一步在本卡里由 `reset_gameboard` 的 emit 完成；这里只为打印"那一刻"的状态
        _line('reset_gameboard 之后', room)

        print('  --- ③ _ai_seat_places_board_now（只在 AI 座位施法时生效）---')
        if caster_is_ai:
            server._ai_seat_places_board_now(room, pid)
            _line('_ai_seat_places_board_now 之后', room, '房间级 state 是否已经回来')
            print('     发出的事件：%s' % [r[0] for r in sent.drain()])
        else:
            print('     （真人施法，不走这一步 —— 等服务端收 place_ships）')

        print('  --- ④ 施法者布完船（place_ships → handle_place_ships）---')
        ships = [{'positions': [{'x': x, 'y': 0}], 'hits': []} for x in range(6)]
        out = server.handle_place_ships({
            'room_id': room.id, 'player_id': pid, 'ships': ships,
        })
        _line('place_ships 之后', room, str(out))
        print('     发出的事件：%s' % [r[0] for r in sent.drain()])

        print('')
        print('  >>> 最终：state=%r current_phase=%r current_attacker=%r'
              % (room.state, room.current_phase, room.current_attacker))
        if room.state == 'rock_paper_scissors':
            print('  >>> ★ 落在了「猜拳」（rock_paper_scissors）—— 玩家/对手要等猜拳才能继续')
        print('')
        return room
    finally:
        sent.uninstall()
        room_manager.rooms.pop(room.id, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--label', default='', help='输出里带的版本标签（脚本本身与版本无关）')
    args = ap.parse_args()
    if args.label:
        print('### 版本标签：%s ###' % args.label)
        print('')
    scenario(False)
    scenario(True)


if __name__ == '__main__':
    main()
