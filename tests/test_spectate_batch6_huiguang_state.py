# -*- coding: utf-8 -*-
"""观战第 6 批 · 死角 B：「回光返照之后房间落到 `rock_paper_scissors`」的判定。

## 上一批留下的疑点

上一批的 E2E 里出现过一次「回光返照重摆之后房间落到 `rock_paper_scissors`」，
作者在工具里加了一步收尾把房间推回 `attacking` —— 那一步在形状上**可能是把真回归
盖掉了**，所以本批必须查清。

## 本批的结论（服务端层复现，不走前端）

复现脚本：`tools/repro_huiguang_room_state.py`（逐帧打印 `state` / `current_phase`）。
当前代码与第 4 批 `59ae6ab`（`_ai_seat_places_board_now` **已经存在**的那一版）
**逐行输出相同** ⇒ 不是第 5 批引入的回归。

落到猜拳的那一步是：

* 施法者是 AI 时，`apply_magic_effect` 里在同一个栈帧里调
  `_ai_seat_places_board_now` → 内部走 `handle_place_ships` → 施法者的
  `huiguang_awaiting_placement` 被消费掉、`room.state` 回到 `attacking`（**正确**）；
* **然后脚本自己**又对**已经摆好船**的座位补发了一次 `place_ships`
  （E2E 的"收尾"那一步）→ `handle_place_ships` 里两个专用分支都已失效
  （`huiguang_awaiting_placement` 已 False、`lingqi_resurgence_applied` 本来就不是），
  于是掉进通用分支 `room.state = 'rock_paper_scissors'`。

⇒ **"房间落到猜拳"是脚本自己多打的那一次调用造成的**，不是被测对象的行为。

## 玩家走得到吗

走不到：`reset_gameboard` 是 `to=caster.sid` **单发**（施法者是 AI 时那个 sid
没有任何连接，真人**收不到**、不会被拽进布船界面；真人施法时他那一份收得到，
而且必须真的摆完才会离开布船界面）。服务端也没有"等一会儿自动替真人摆"的兜底。

⚠️ 唯一能碰到这条路的形态是**重复调用 `handle_place_ships`**（同一个座位发两次
`place_ships`）。服务端**确实没有**"棋盘没在等摆放就拒绝"的闸门 ——
本批**没有**去加那道闸门：那会改变既有行为（灵气复苏 / 败者食尘 / 开局布船
都共用这个入口），而且**没有任何玩家路径能发出那第二次调用**。
本文件把这条**既有行为**钉成用例：它今天是什么样、将来谁要改它就会红。
"""
import json
import os
import pathlib
import sys
import uuid

import pytest

import db as db_module
import server
from server import GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

ROOT = pathlib.Path(__file__).resolve().parent.parent
SID_A = 'spec6b-sid-a'
SID_B = 'spec6b-sid-b'
AI_ID = 'ai-spec6b'

_ACCOUNTS = {}


def _account(key):
    if key not in _ACCOUNTS:
        uid = db_module.create_user('spec6b-%s-%s' % (key, uuid.uuid4().hex[:10]), 'x' * 12)
        assert uid, '建测试账号失败'
        _ACCOUNTS[key] = uid
    return _ACCOUNTS[key]


class _Silent:
    """把服务端发出去的事件吞掉并记账（本文件主要看**房间状态**，顺带看收件人）。"""

    def install(self):
        self._emit, self._sio = server.emit, server.socketio.emit
        self.sent = []
        self.reset_targets = []

        def _spy(event, *a, **kw):
            self.sent.append(event)
            if event == 'reset_gameboard':
                self.reset_targets.append(kw.get('to'))
            return None

        server.emit = _spy
        server.socketio.emit = _spy
        return self

    def uninstall(self):
        server.emit, server.socketio.emit = self._emit, self._sio


@pytest.fixture
def quiet():
    spy = _Silent().install()
    yield spy
    spy.uninstall()


def _ships(row):
    return [PlayerShip(positions=[Position(x, row)], hits=[]) for x in range(6)]


def _make_huiguang_room(caster_is_ai):
    room = GameRoom('spec6b-hg-%s' % ('ai' if caster_is_ai else 'human'))
    caster = AI_ID if caster_is_ai else SID_A
    room.players[caster] = Player(
        name='甲', ships=_ships(0), attacks=[], remaining_ships=6,
        sid=caster, user_id=None if caster_is_ai else _account('alpha'))
    room.players[SID_B] = Player(
        name='乙', ships=_ships(5), attacks=[], remaining_ships=6,
        sid=SID_B, user_id=_account('beta'))
    room.state = 'attacking'
    room.current_phase = 'preparation'
    room.current_attacker = caster           # 回光返照要求自己先手
    room.attack_order = [caster, SID_B]
    room.attacks_remaining = 6
    room.round = 3
    room.ranked = False
    room.game_logs = []
    room.is_ai_room = bool(caster_is_ai)
    if caster_is_ai:
        room.ai_difficulty = 'easy'
    room.players[caster].attacks.append(Position(x=1, y=5, hit=True, ship_sunk=False))
    room.players[SID_B].attacks.append(Position(x=2, y=0, hit=False, ship_sunk=False))
    room_manager.rooms[room.id] = room
    return room, caster


def _place(room, pid):
    ships = [{'positions': [{'x': x, 'y': 0}], 'hits': []} for x in range(6)]
    return server.handle_place_ships({'room_id': room.id, 'player_id': pid, 'ships': ships})


# ===========================================================================
# 1. 打出回光返照之后，房间**本来就在 attacking**（不需要任何工具侧补救）
# ===========================================================================
@pytest.mark.parametrize('caster_is_ai', [False, True])
def test_huiguang_leaves_the_room_in_attacking(quiet, caster_is_ai):
    """★★ 施法者摆完船之后 `room.state` 必须是 `attacking`。

    · 真人施法：施法者自己发 `place_ships` 之后 → `attacking` / `preparation` /
      攻击次数 0（作者裁定的"能进战斗阶段但打不出去"）。
    · AI 施法：`apply_magic_effect` 在**同一个栈帧**里就把它摆完
      （`_ai_seat_places_board_now`），`apply_magic_effect` 返回时**已经**是 attacking。

    改坏哪一行会红：把 `_ai_seat_places_board_now(room, caster_id)` 那一句删掉
    （AI 施法那条会停在 `placing_ships`）；或把 `handle_place_ships` 里
    `huiguang_awaiting_placement` 分支删掉（两条都会变成猜拳）。
    """
    room, caster = _make_huiguang_room(caster_is_ai)
    try:
        res = server.apply_magic_effect(room, caster, MagicCard('回光返照'), {})
        assert res.success is not False, getattr(res, 'message', res)

        if caster_is_ai:
            # ★ AI 就地摆完 ⇒ 出函数时状态已经回来了（**看不到**中间那段 placing_ships）
            assert room.state == 'attacking', \
                'AI 座位施法后房间没有回到 attacking（实际 %r）—— 对手会看到布船屏' % room.state
            assert room.current_phase == 'preparation'
            assert room.attacks_remaining == 0, '「跳过自己的战斗阶段」= 攻击次数 0'
            return

        # 真人施法：必须**停在** placing_ships 等他摆（服务端不许替他摆）
        assert room.state == 'placing_ships', \
            '真人施法时房间应当停下等他摆放（实际 %r）' % room.state
        assert not room.players[caster].ships, '真人的棋盘已被清空，等他重摆'
        out = _place(room, caster)
        assert out.get('status') == 'success', out
        assert room.state == 'attacking', \
            '真人施法、布完船之后房间应该回到 attacking（实际 %r）' % room.state
        assert room.current_phase == 'preparation'
        assert room.current_attacker == caster, '行动权仍然在施法者自己手上'
        assert room.attacks_remaining == 0
        assert room.game_effects.get('zero_attacks_for', {}).get('player') == caster, \
            '攻击次数归零必须是**玩家级**标记（zero_attacks_for），不是房间级的'
    finally:
        room_manager.rooms.pop(room.id, None)


# ===========================================================================
# 2. ★ 既有行为：**对已经摆好的座位再发一次 `place_ships`** 会让房间落到猜拳
# ===========================================================================
def test_duplicate_place_ships_is_what_sends_the_room_to_rps(quiet):
    """★★ 这道题的正解：让房间落到 `rock_paper_scissors` 的**不是**回光返照，

    是"对已经摆好的座位**第二次**调用 `handle_place_ships`"。
    上一批 E2E 的收尾**无条件**补发了那一次调用 ⇒ 房间落到猜拳 ⇒ 工具再推回 attacking
    ⇒ **看起来**像"回光返照会让房间落到猜拳"（把真因盖住了）。

    判据分三步，每步都断言，所以"是谁把它弄成猜拳的"一目了然：
      ① AI 施法 + 就地摆放之后 —— `attacking`（第一次调用，正常收尾）；
      ② 再对同一个座位发一次 `place_ships` —— 服务端**照收**（返回 success）
         且房间变成 `rock_paper_scissors`；
      ③ 这一次调用是**多余**的：它把 `huiguang_awaiting_placement` 的收尾
         整条绕过去了（那个标记在第 ① 步就已经被消费掉）。

    ⚠️ 这是**既有行为**，不是第 5 批引入的：`tools/repro_huiguang_room_state.py`
       在 `59ae6ab` 与当前代码上输出逐行相同。本用例把它钉住，
       谁将来加了"没在等摆放就拒绝"的闸门，这条会红 —— 那时应当**一起改这条注释**，
       而不是当成 bug 去压。
    """
    room, caster = _make_huiguang_room(caster_is_ai=True)
    try:
        server.apply_magic_effect(room, caster, MagicCard('回光返照'), {})
        # ① AI 就地摆完
        assert room.state == 'attacking', '① AI 就地摆放之后应当是 attacking'
        assert room.players[caster].ships, 'AI 的船确实摆上了'
        assert not room.huiguang_awaiting_placement, '① 那个标记已经被收尾消费掉'

        # ② 同一个座位**再发一次**（上一批 E2E 收尾就是这么干的）
        again = _place(room, caster)
        assert again.get('status') == 'success', \
            '服务端**没有**"没在等摆放就拒绝"的闸门（这是既有行为，本批不改）：%r' % again
        assert room.state == 'rock_paper_scissors', \
            '第二次 place_ships 才会把房间推进猜拳（实际 %r）—— 这就是那条现象的真因' \
            % room.state
        # ③ 对照：把同一局从头再来一次，**只要不发那第二次**，房间就停在 attacking
        room2, caster2 = _make_huiguang_room(caster_is_ai=True)
        try:
            server.apply_magic_effect(room2, caster2, MagicCard('回光返照'), {})
            assert room2.state == 'attacking', \
                '对照腿：不发第二次 place_ships 时房间不会落到猜拳'
        finally:
            room_manager.rooms.pop(room2.id, None)
    finally:
        room_manager.rooms.pop(room.id, None)


def test_the_duplicate_call_is_not_reachable_from_a_real_player_path(quiet):
    """★ 为什么"既有行为"不等于"玩家会卡住"：`reset_gameboard` 是单发的。

    施法者是 AI 时那份 `reset_gameboard` 发给 `'ai-'+room_id`（**没有这条连接**），
    真人**收不到** ⇒ 前端不会把他拽进布船界面 ⇒ 他没有任何入口发出第二次
    `place_ships`。这条用例把"发给了谁"钉住（**不是**断言"前端不会"）。
    """
    room, caster = _make_huiguang_room(caster_is_ai=True)
    try:
        server.apply_magic_effect(room, caster, MagicCard('回光返照'), {})
        targets = [e for e in quiet.sent]
        assert 'reset_gameboard' in targets, '一条 reset_gameboard 都没发'
        assert quiet.reset_targets, 'reset_gameboard 没带 to= 收件人'
        assert all(t == caster for t in quiet.reset_targets), \
            '`reset_gameboard` 不该发给对手（实际收件人 %s）' % quiet.reset_targets
        # 对照：对手的 sid 是真人（有连接），所以"发给 AI 的 sid"= 没人收得到
        assert quiet.reset_targets == [AI_ID], \
            '施法者是 AI 时，那份重摆事件应当只发往 AI 的 sid（实际 %s）' % quiet.reset_targets
        assert room.players[SID_B].sid == SID_B != AI_ID
    finally:
        room_manager.rooms.pop(room.id, None)
