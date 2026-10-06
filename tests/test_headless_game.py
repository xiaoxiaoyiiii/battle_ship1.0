# -*- coding: utf-8 -*-
"""无头对局驱动器（`tools/headless_game.py`）的回归用例。

这些用例钉的是驱动器本身的契约 —— 它不是产品逻辑，而是**度量工具**：
胜率、卡死率、动作序列能不能复现，全都取决于它。工具假绿比产品假红更危险
（CLAUDE.md 第 10.15 条「工具假红先怀疑工具」，反过来同样成立），
所以这里既测"跑得通"，也测"不许假装跑通了"。

⚠️ 本文件直调 `server.py` 的 handler，所以必须先把 `BATTLESHIP_DB_PATH`
指到临时目录（`tests/conftest.py` 已经做了，这里再兜一次，防止有人单独跑本文件）。
"""
import os
import pathlib
import tempfile

_TMP_DB_DIR = pathlib.Path(tempfile.mkdtemp(prefix='battleship-headless-'))
os.environ.setdefault('BATTLESHIP_DB_PATH', str(_TMP_DB_DIR / 'battleship.db'))

import pytest  # noqa: E402

import server  # noqa: E402
from tools import headless_game as hg  # noqa: E402


def _hard():
    return hg.ExistingAIPolicy('hard')


def _random():
    return hg.RandomPolicy()


def _rooms_snapshot():
    return dict(server.room_manager.get_all_rooms())


# ---------------------------------------------------------------------------
# 1. 一局能正常打完
# ---------------------------------------------------------------------------
def test_full_game_completes_with_winner():
    result = hg.play_game(_hard, _hard, seed=1, max_rounds=60)

    assert not result.stalled, f'不该卡死：{result.stall_reason}'
    assert result.winner in (result.p1, result.p2), f'winner 异常：{result.winner}'
    assert result.rounds >= 1
    assert len(result.actions) < 4000, '动作数应远低于上限'
    # 必须有实际打过的炮 —— 只有"摆船+猜拳"就判胜负说明驱动器漏了回合推进
    assert any(kind == 'attack' for kind, _, _ in result.actions)
    assert any(kind == 'end_turn' for kind, _, _ in result.actions)




# ---------------------------------------------------------------------------
# 2. 可复现：同种子 → 同一个 winner / rounds / 动作序列
# ---------------------------------------------------------------------------
def _seat_normalize(result):
    """把结果里的座位 id 换成 'p1'/'p2'（含 winner）。

    房间 id 是 uuid4、AI 座位 id 是 `'ai-'+room_id` → 两次跑必然不同，
    直接比 `winner` 字符串永远失败。这不是"不确定"，只是 id 空间不同。
    """
    mapping = {result.p1: 'p1', result.p2: 'p2'}
    return {
        'winner': mapping.get(result.winner, result.winner),
        'rounds': result.rounds,
        'hash': result.action_hash(),
        'actions': [(k, mapping.get(p, p), d) for k, p, d in result.actions],
    }








# ---------------------------------------------------------------------------
# 3. 种子确实起作用
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 4. ExistingAIPolicy 真的比随机强（松边界，别写成 flaky）
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# 4b. ★「打疼了没有」—— 作者实报的「我甚至可以无伤赢他」在胜率里看不见
# ---------------------------------------------------------------------------
#
# 背景（2026-09-22）：验收指标此前**只有胜率**。而 68.8% 同时兼容两种对局：
#   · 每一局都互有攻防、双方各沉 5 艘的险胜；
#   · 对手从头到尾没打中过我，我只是靠卡牌效果赢。
# 作者报的是后者，但它在这套指标里**一个数字都对不上**。所以先把量做出来：
#   击沉对方 / 被击沉 / 炮击击沉事件 / 命中率 / 无伤获胜。
# 这里钉的是"这几个量真的在数、数得对、且不引入新的随机源"。











# ---------------------------------------------------------------------------
# 4c. ★ 度量工具本身必须可复现（"对照组"最容易悄悄长出熵随机源）
# ---------------------------------------------------------------------------
#
# 事故（2026-09-22 实测，不是推演）：
#   `tools/master_ablation.py` 的 `_plain_attack`（"不看情报、均匀撒"的对照档）
#   写的是 `rng = rng or random.Random()`。无参 `random.Random()` 用**系统熵**播种，
#   于是"同一 seed 连跑两次"胜率 **72.0% vs 70.7%**，动作哈希也不同。
#   此前记下的"读情报值多少分"就是这个噪声。
#   同形状的还有 `tools/master_aggression_ablation.py` 里那份抄过去的实现
#   （已修）。守住它的成本很低，而它坏掉**不会有任何症状**。





# ---------------------------------------------------------------------------
# 5. 硬上限：撞上限要记 stalled，既不挂也不抛
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# 6. 驱动器不许留下房间
# ---------------------------------------------------------------------------




def test_room_is_removed_even_if_run_raises():
    before = set(_rooms_snapshot())

    class Boom(hg.Policy):
        def place_ships(self, room, pid):
            raise RuntimeError('boom')

    result = hg.play_game(Boom, Boom, seed=11)
    assert result.violations
    assert set(_rooms_snapshot()) == before




# ---------------------------------------------------------------------------
# 7. 无头前提本身（这些一旦不成立，整套度量就失真）
# ---------------------------------------------------------------------------












def test_random_policy_only_plays_legal_cards():
    """随机策略必须筛掉"当前打不出去"的卡，否则一局被拒几千次、fuzz 没内容。"""
    results = hg.run_many(_random, _random, games=6, seed=606,
                          max_rounds=40, max_actions=1200)
    rejected = [v for r in results for v in r.violations if '出牌被拒' in v]
    total = sum(len(r.actions) for r in results)
    assert len(rejected) <= total * 0.05, f'出牌被拒占比过高：{len(rejected)}/{total}'








def test_master_vs_hard_runs_without_stalling():
    """★ 大师对困难跑一小批，**一局都不许卡死**。

    卡死是这个功能最贵的失败模式（AI 回合永远交不出去、真人干等）。
    1000 局级的度量在 CI 里太慢，这里取一个能跑得快、又足够撞出
    「打出去的卡留下待办」这类问题的局数。
    """
    results = hg.run_many(lambda: hg.make_policy('master'),
                          lambda: hg.make_policy('hard'), games=60, seed=11)
    stalled = [r for r in results if r.stalled]
    assert not stalled, '大师有 %d 局卡死，例如 seed=%s 原因=%s' % (
        len(stalled), stalled[0].seed if stalled else None,
        stalled[0].stall_reason if stalled else None)
