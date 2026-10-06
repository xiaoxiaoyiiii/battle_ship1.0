# -*- coding: utf-8 -*-
"""反作弊引擎单测（`anticheat.py`）。

核心要求：
  * **真实作弊形态必须被抓到** —— 用 `docs/ANTICHEAT_FORENSICS_2026_09_19.md` 里
    的真实数据特征构造用例（不是编一个"看起来像"的）；
  * **正常对局必须不被误伤** —— 反作弊最严重的失败是误杀正常玩家；
  * **判定是纯函数** —— 同样输入永远同样输出，且绝不抛异常（失败开放）。
"""
import anticheat as ac


# ===========================================================================
# 一、真实作弊形态：必须抓到
# ===========================================================================
def test_sweep_perfect_win_caught():
    """本库真实手法：单方第 1 回合六发全沉、另一方一枪未发 → block 档。

    ★ 判据**不依赖 user_id / socket sid 对齐**（它们本就是两套 id，
    第一版规则拿它们比对 → 在真实数据上召回率 0%）。
    """
    r = ac.evaluate({
        'rounds': 1,
        'attackers': ['sid-A'],
        'max_hits': 6,
        'foe_ships': 6,
    })
    assert 'sweep_perfect_win' in r['rules']
    assert r['blocked'] is True
    assert r['score'] >= ac.LEVEL_BLOCK










def test_mirror_positions_caught():
    """对手船位与历史完全一致 → 固定靶子指纹。"""
    sig = '0,0|1,0|2,0|3,0|4,0|5,0'
    r = ac.evaluate({
        'foe_position_signature': sig,
        'past_signatures': [sig, sig],
    })
    assert 'mirror_positions' in r['rules']




def test_instant_surrender_caught():
    """见面就投：已开打、第 1 回合、双方零交火。"""
    r = ac.evaluate({
        'ended_by': 'surrender',
        'rounds': 1,
        'attacker_total_hits': 0,
        'defender_total_hits': 0,
    })
    assert 'instant_surrender' in r['rules']
    assert r['score'] >= ac.LEVEL_FLAG








def test_repeat_opponent_burst_caught():
    """5 分钟内反复撞同一个人 → 同时排队对刷。"""
    r = ac.evaluate({'opponent_gaps_sec': [45, 30, 52, 38]})
    assert 'repeat_opponent_burst' in r['rules']
    assert r['score'] >= ac.LEVEL_FLAG








def test_zero_engagement_loss_caught():
    r = ac.evaluate({'rounds': 5, 'loser_total_hits': 0,
                     'foe_ships': 6, 'total_ships': 12})
    assert 'zero_engagement_loss' in r['rules']


def test_suspicious_timing_caught():
    r = ac.evaluate({'since_last_match_sec': 12})
    assert 'suspicious_timing' in r['rules']






# ===========================================================================
# 二、组合形态：多个信号累加，冲到 block
# ===========================================================================
def test_full_farm_match_blocks():
    """一局典型的刷分局：横扫 + 短间隔 + 一边倒 → 必须拦下结算。"""
    r = ac.evaluate({
        'rounds': 1,
        'attackers': ['sid-A'],
        'max_hits': 6,
        'foe_ships': 6,
        'since_last_match_sec': 15,
        'opponent_total_games': 104,
        'opponent_wins': 104,
        'opponent_losses': 0,
        'opponent_gaps_sec': [45, 30, 52],
        'ranked_win_streak': 30,
    })
    assert r['blocked'] is True
    assert r['score'] >= ac.LEVEL_BLOCK
    # 必须能解释清楚
    assert len(r['reasons']) >= 4


# ===========================================================================
# 三、正常对局：绝不许误伤
# ===========================================================================
def test_normal_match_is_clean():
    """一场正常的、打了 12 回合的势均力敌对局 → 必须完全干净。"""
    r = ac.evaluate({
        'rounds': 12,
        'sunk': 6,
        'foe_ships': 6,
        'foe_hits_on_winner': 4,
        'attacker_total_hits': 18,
        'defender_total_hits': 15,
        'loser_total_hits': 15,
        'since_last_match_sec': 900,
        'duration_sec': 480,
        'opponent_total_games': 3,
        'opponent_wins': 2,
        'opponent_losses': 1,
        'opponent_gaps_sec': [3600, 7200],
        'ranked_win_streak': 2,
        'ended_by': 'attacks',
    })
    assert r['level'] == 'clean'
    assert r['score'] == 0
    assert r['reasons'] == []
    assert r['blocked'] is False


def test_fast_legit_win_not_blocked():
    """高手速胜：3 回合打赢，但对手有还手 → 不该被拦。"""
    r = ac.evaluate({
        'rounds': 3,
        'sunk': 6,
        'foe_ships': 6,
        'foe_hits_on_winner': 2,
        'loser_total_hits': 2,
        'since_last_match_sec': 600,
    })
    assert r['blocked'] is False
    assert 'sweep_perfect_win' not in r['rules']


# ===========================================================================
# 四、健壮性：失败开放、纯函数
# ===========================================================================




def test_garbage_types_do_not_raise():
    """脏数据（字符串、None、乱类型）绝不许抛 —— 否则会把对局结算搞崩。"""
    r = ac.evaluate({
        'rounds': 'abc',
        'sunk': None,
        'foe_ships': [],
        'opponent_gaps_sec': 'not-a-list',
        'past_signatures': None,
        'duration_sec': object(),
    })
    assert isinstance(r['score'], int)


def test_deterministic():
    """纯函数：同样输入永远同样输出。"""
    facts = {'rounds': 1, 'sunk': 6, 'foe_ships': 6, 'foe_hits_on_winner': 0}
    a = ac.evaluate(dict(facts))
    b = ac.evaluate(dict(facts))
    assert a == b
