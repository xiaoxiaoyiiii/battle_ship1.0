# -*- coding: utf-8 -*-
"""「攻击次数没打完、但 36 格已全打过」导致的回合死锁（2026-09-21 修）。

## 症状

一个玩家可能**还有剩余攻击次数、但棋盘 36 格已经全部轰过**。此时：

  · `handle_attack`          → 拒绝每个目标（「你已经攻击过这个位置了」）
  · `handle_enter_end_phase` → 因为「你还有剩余攻击次数」拒绝交阶段

⇒ **没有任何合法动作能结束这个回合**，双方永久烂在那里。

## 为什么不是罕见边界

每回合攻击次数 = 存活船数（6 艘），而棋盘只有 36 格
⇒ 约 **6-7 个回合**就能把整个棋盘打完。这不是只有 AI 会碰到的角落，
**真人一样会中招**。

## 为什么 90 秒超时兜底也救不回来

`_auto_act_on_timeouts` 在「没有可打的格子」时，正是去调
`handle_enter_end_phase` —— 而那个调用**同样被上面那条门禁拒绝**，
于是看门狗每轮空转，永远推不动。所以这个 bug 不是「偶尔卡一下」，
而是**当场烂死**。

## 修法

`_attackable_cells(room, pid)` 成为**唯一一份**「还能打哪些格」的实现；
门禁改成「还有攻击次数 **且** 还有能打的格子」才拦。
另外两处原本各写一遍的同一段网格数学（AI 炮击循环 / 超时看门狗）也统一读它。

## 复现来源（不是推演出来的）

无头模拟器抓到：`--games 300 --p1 hard --p2 random --seed 3000`
修复前 seed **3102** 以「连续 60 个动作后房间状态无任何变化」卡死，
房间自述正是：
`attacks_remaining=2, last_attack_error='36 格全部打过，仍有 2 次攻击次数'`。
修复后同一批 seed 里该局正常结束，且所有卡死样本的 `last_attack_error` 全为空。
"""
import os
import pathlib
import re
import tempfile

_TMP_DB_DIR = pathlib.Path(tempfile.mkdtemp(prefix='battleship-deadlock-'))
os.environ.setdefault('BATTLESHIP_DB_PATH', str(_TMP_DB_DIR / 'battleship.db'))

import pytest  # noqa: E402

import server  # noqa: E402
from server import Player, Position  # noqa: E402
from tools import headless_game as hg  # noqa: E402

SERVER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'server.py')

ALL_36 = [(x, y) for x in range(6) for y in range(6)]


def _mk_room_with(attacked_cells):
    """造一个最小房间：一个玩家，攻击历史 = attacked_cells。"""
    room = server.GameRoom('r-deadlock')
    room.players['p1'] = Player(name='P1', ships=[], remaining_ships=6,
                                attacks=[Position(x, y) for x, y in attacked_cells],
                                sid='p1')
    return room


# ---------------------------------------------------------------------------
# 辅助函数本身
# ---------------------------------------------------------------------------

def test_attackable_cells_lists_what_is_left():
    room = _mk_room_with([(0, 0), (1, 0)])
    left = server._attackable_cells(room, 'p1')
    assert len(left) == 34
    assert (0, 0) not in left and (1, 0) not in left
    assert (2, 0) in left


def test_attackable_cells_empty_when_board_exhausted():
    """★ 这正是卡死的那一刻：36 格全打过 → 一个能打的格都没有。"""
    room = _mk_room_with(ALL_36)
    assert server._attackable_cells(room, 'p1') == []


def test_attackable_cells_unknown_player_is_empty_not_crash():
    room = _mk_room_with([])
    assert server._attackable_cells(room, 'nobody') == []
    assert server._attackable_cells(None, 'p1') == []


# ---------------------------------------------------------------------------
# ★ 核心回归：门禁必须放行「次数还有、但无处可打」
# ---------------------------------------------------------------------------

def test_guard_lets_you_leave_when_nothing_is_left_to_attack():
    """★ 修复的核心判据：门禁的拦截条件必须**同时**要求「还有能打的格」。

    修复前判据只有 `attacks_remaining > 0` → 36 格全打过时仍然拦，
    玩家/AI 就再也交不出回合了。这里把改写后的判据钉死。
    """
    room = _mk_room_with(ALL_36)
    room.attacks_remaining = 2
    pid = 'p1'

    # 修复后的门禁表达式（与 handle_enter_end_phase 内联的那一行保持一致）
    blocked = room.attacks_remaining > 0 and server._attackable_cells(room, pid)
    assert not blocked, '36 格全打过时不该再拦 —— 否则这个回合永远结束不了'

    # 反面对照：还有格子可打时必须继续拦（不能把正常规则一起放开）
    room2 = _mk_room_with([(0, 0)])
    room2.attacks_remaining = 2
    assert room2.attacks_remaining > 0 and server._attackable_cells(room2, 'p1')

    # 反面对照：没有攻击次数时本来就不拦
    room3 = _mk_room_with([(0, 0)])
    room3.attacks_remaining = 0
    assert not (room3.attacks_remaining > 0 and server._attackable_cells(room3, 'p1'))


# ---------------------------------------------------------------------------
# ★ 源码级：那三处网格数学不许再各写一遍
# ---------------------------------------------------------------------------

def test_four_call_sites_use_the_shared_helper():
    """四处调用点都要读同一个 helper，而不是各自内联算。

    原本「还能打哪些格」在 server.py 里有**四份**：
      ① `handle_enter_end_phase` 的结束阶段门禁
      ② `_ai_turn_loop` 的炮击循环
      ③ `_auto_act_on_timeouts` 的超时兜底
      ④ 自动连击里挑随机目标那段
    现在四处都走 `_attackable_cells`。

    ⚠️ 这里**刻意只查调用点数量，不查"那段数学只出现一次"**。
       因为 `(a.x, a.y) for a in ...attacks` 这个形状还有两处**合法**用途
       （`_find_safe_placement` / 落点校验，用的是**对方**的攻击历史
       ——「哪里是安全落点」，与「我还能打哪里」是两个概念）。
       拿它当"重复实现"的判据会误报。真正管住回归的是上面那些
       单元测试与真实 seed 的端到端测试；这条只好管"有没有人把 helper 删了"。
    """
    src = open(SERVER_PATH, encoding='utf-8').read()
    assert 'def _attackable_cells(' in src, '_attackable_cells 不见了'
    n = src.count('_attackable_cells(room,')
    assert n >= 4, '至少应有 4 处调用，实际 %d 处（有人又内联算了一遍？）' % n


# ---------------------------------------------------------------------------
# ★ 端到端：拿真实复现的那个 seed 钉
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('seed', [3102, 3038, 3043, 3046, 3106, 3115])
def test_repro_seeds_no_longer_deadlock_on_attack(seed):
    """★ seed 3102 是修复前**实测卡死**的那一局。

    卡死原因必须**不是**「36 格全部打过」——那个失败模式已经修掉。
    允许它以别的原因结束（例如随机对局打满 200 回合上限，那是合法结果），
    但绝不允许它再因为「打不动了」停住。
    """
    r = hg.play_game(lambda: hg.ExistingAIPolicy('hard'),
                     lambda: hg.RandomPolicy(), seed=seed, max_rounds=200)
    assert '全部打过' not in (r.stall_reason or ''), (
        'seed=%d 又出现了攻击死锁: %s' % (seed, r.stall_reason))


def test_board_exhaustion_never_stalls_a_batch():
    """批量跑一批：任何一局的卡死原因都不许是攻击死锁。

    比单 seed 更宽 —— 万一修复被回退，这一批里大概率会撞出来。
    """
    results = hg.run_many(lambda: hg.ExistingAIPolicy('hard'),
                          lambda: hg.RandomPolicy(), games=120, seed=3000)
    bad = [r for r in results if '全部打过' in (r.stall_reason or '')]
    assert not bad, '有 %d 局死于攻击死锁，例如 seed=%s' % (
        len(bad), bad[0].seed if bad else None)
