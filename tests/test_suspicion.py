# -*- coding: utf-8 -*-
"""嫌疑度累计与阶梯封禁单测（`suspicion.py`）。

这个模块决定**谁被封**，是整个反作弊里后果最重的一段。所以测试要覆盖：
  A. 衰减正确（老的作弊会淡出 —— 人不是永远有罪）
  B. 阶梯正确（阈值、能力判定、逐级收紧）
  C. ★ **正常玩家绝不被封**（最重要：一次误判 = 一个真玩家被赶走）
  D. 管理员覆盖优先于算法，且可双向（调高/调低）
  E. 纯函数 / 失败开放
"""
import suspicion as sp


# ===========================================================================
# A. 时间衰减
# ===========================================================================
def test_decay_zero_age_is_one():
    assert sp.decay_factor(0) == 1.0


def test_decay_half_life():
    """半衰期 14 天 → 14 天后权重减半。"""
    assert abs(sp.decay_factor(sp.DECAY_HALF_LIFE_DAYS) - 0.5) < 1e-9
    assert abs(sp.decay_factor(sp.DECAY_HALF_LIFE_DAYS * 2) - 0.25) < 1e-9


def test_decay_never_reaches_zero():
    """永远 > 0（只是趋近）—— 不许因为"太久"就完全抹掉记录。"""
    assert sp.decay_factor(100000) > 0


def test_decay_negative_age_clamped():
    """负的 age（时钟回拨）当成 0，不许放大成 >1。"""
    assert sp.decay_factor(-5) == 1.0


def test_old_cheating_fades_out():
    """★ 90 天前的作弊，贡献应远小于昨天 —— 人不是永远有罪。"""
    recent = sp.accumulate([{'score': 100, 'age_days': 1}])
    old = sp.accumulate([{'score': 100, 'age_days': 90}])
    assert old < recent * 0.05, f'90 天前的贡献应几乎消失，实际 {old} vs {recent}'


# ===========================================================================
# B. 阶梯与能力
# ===========================================================================
def test_accumulate_sums_with_decay():
    """两局都是"今天"，应当直接相加。"""
    total = sp.accumulate([
        {'score': 100, 'age_days': 0},
        {'score': 100, 'age_days': 0},
    ])
    assert abs(total - (200 / sp.SCORE_DIVISOR)) < 1e-6


def test_clean_match_adds_nothing():
    """单局嫌疑度 0 的对局不贡献任何东西（正常玩家堆再多局也是 0）。"""
    total = sp.accumulate([{'score': 0, 'age_days': 0}] * 50)
    assert total == 0.0


def test_level_thresholds():
    """阈值：100 → 禁排位，200 → 禁匹配，300 → 禁房间。"""
    assert sp.level_from_score(0) == 0
    assert sp.level_from_score(99.9) == 0
    assert sp.level_from_score(100) == 1
    assert sp.level_from_score(199) == 1
    assert sp.level_from_score(200) == 2
    assert sp.level_from_score(300) == 3
    assert sp.level_from_score(99999) == 3


def test_capability_tightens_by_level():
    """等级越高，被禁的能力越多（逐级收紧，且是**包含**关系）。"""
    # 0 级：全都能用
    for cap in (sp.CAP_RANKED, sp.CAP_MATCH, sp.CAP_ROOM):
        assert sp.capability_allowed(0, cap) is True
    # 1 级：只禁排位
    assert sp.capability_allowed(1, sp.CAP_RANKED) is False
    assert sp.capability_allowed(1, sp.CAP_MATCH) is True
    assert sp.capability_allowed(1, sp.CAP_ROOM) is True
    # 2 级：禁排位 + 禁匹配
    assert sp.capability_allowed(2, sp.CAP_RANKED) is False
    assert sp.capability_allowed(2, sp.CAP_MATCH) is False
    assert sp.capability_allowed(2, sp.CAP_ROOM) is True
    # 3 级：全禁
    for cap in (sp.CAP_RANKED, sp.CAP_MATCH, sp.CAP_ROOM):
        assert sp.capability_allowed(3, cap) is False


def test_blocked_capabilities_list():
    assert sp.blocked_capabilities(0) == []
    assert sp.blocked_capabilities(1) == [sp.CAP_RANKED]
    assert set(sp.blocked_capabilities(2)) == {sp.CAP_RANKED, sp.CAP_MATCH}
    assert len(sp.blocked_capabilities(3)) == 3


def test_next_threshold():
    assert sp.next_threshold(0) == 100.0
    assert sp.next_threshold(90) == 10.0
    assert sp.next_threshold(100) == 100.0      # 距 200
    assert sp.next_threshold(300) == 0.0        # 已到顶


def test_unknown_capability_is_allowed():
    """未知能力不拦（失败开放）—— 绝不能因为拼错参数就把人拦死。"""
    assert sp.capability_allowed(3, 'no_such_cap') is True


def test_denial_message_only_when_blocked():
    assert sp.denial_message(0, sp.CAP_RANKED) == ''
    msg = sp.denial_message(1, sp.CAP_RANKED)
    assert '排位' in msg
    assert sp.denial_message(1, sp.CAP_MATCH) == ''


def test_denial_message_does_not_leak_detection_details():
    """★ 拒绝文案**不许**透露判据细节（那等于教作弊者怎么规避）。"""
    msg = sp.denial_message(3, sp.CAP_ROOM)
    for leak in ('sweep', '横扫', '第1回合', '六', '命中', '规则', 'score', '嫌疑度'):
        assert leak not in msg, f'文案泄露了判据细节: {leak}'


# ===========================================================================
# C. ★ 正常玩家绝不被封
# ===========================================================================
def test_normal_player_never_banned():
    """★ 一个正常玩家打 500 局、每局嫌疑度都是低分（record 档 30）也**不该被封**。

    30 / 5 = 6 一局；但正常局根本不会是 30 —— 这里给一个**极端宽松**的假设：
    假设他有 10 局被误判成 record(30)，且都是今天：
    10 * 6 = 60 < 100 → 仍然不封。这是"给误判留容错"的量化体现。
    """
    matches = [{'score': 30, 'age_days': 0}] * 10
    score = sp.accumulate(matches)
    assert score < 100, f'10 局低分误判不该导致封禁，实际 {score}'
    assert sp.level_from_score(score) == 0


def test_many_clean_matches_never_ban():
    """500 局全是正常对局（score 0）→ 嫌疑度恒为 0。"""
    score = sp.accumulate([{'score': 0, 'age_days': 0}] * 500)
    assert score == 0.0
    assert sp.level_from_score(score) == 0


def test_real_farmer_gets_banned():
    """★ 真实刷分者（每天十几局 block 档，持续几天）→ 必须被封。

    用本库真实的作弊形态：一个人 100 局里大量 block(100)。
    """
    matches = [{'score': 100, 'age_days': 0.5}] * 100
    score = sp.accumulate(matches)
    assert score >= 300, f'真实刷分者必须到最高档，实际 {score}'
    assert sp.level_from_score(score) == sp.LEVEL_NO_ROOM


# ===========================================================================
# D. 管理员覆盖
# ===========================================================================
def test_override_clears_ban():
    """★ 管理员解封 → 立刻回到 0 级（人的决定优先于算法）。"""
    assert sp.effective_level(500, {'cleared': True}) == 0


def test_override_sets_level():
    """管理员可以直接指定等级（调高）。"""
    assert sp.effective_level(0, {'level': 2}) == 2


def test_override_outranks_score():
    """覆盖优先于算法，双向都成立。"""
    assert sp.effective_level(0, {'level': 3}) == 3      # 算法说正常，人说要封
    assert sp.effective_level(500, {'level': 0}) == 0    # 算法说要封，人说正常


def test_no_override_uses_algorithm():
    assert sp.effective_level(250) == 2
    assert sp.effective_level(250, None) == 2
    assert sp.effective_level(250, {}) == 2


def test_garbage_override_falls_back_to_algorithm():
    """脏覆盖值不许抛，也不许把人静默放行。"""
    assert sp.effective_level(250, {'level': 'abc'}) == 2
    assert sp.effective_level(250, 'nonsense') == 2
    assert sp.effective_level(250, {'level': 999}) == 3   # 夹到上限


# ===========================================================================
# E. 报告组装 / 健壮性
# ===========================================================================
def test_build_report_shape():
    r = sp.build_report('u1', [{'score': 100, 'age_days': 0}] * 5, username='甲')
    assert r['user_id'] == 'u1'
    assert r['username'] == '甲'
    assert r['level'] == 1
    assert r['level_name'] == '禁止排位'
    assert sp.CAP_RANKED in r['blocked']
    assert r['overridden'] is False


def test_build_report_marks_override():
    r = sp.build_report('u1', [], override={'cleared': True, 'reason': '误判'})
    assert r['overridden'] is True
    assert r['override_reason'] == '误判'
    assert r['level'] == 0


def test_build_report_is_json_safe():
    """报告必须能直接 JSON 化（不许夹带服务端活对象）。"""
    import json
    r = sp.build_report('u1', [{'score': 100, 'age_days': 1}], username='甲')
    json.dumps(r)          # 不抛即通过


def test_accumulate_tolerates_garbage():
    """脏数据不许抛（失败开放）。"""
    assert sp.accumulate(None) == 0.0
    assert sp.accumulate([{'score': 'abc'}]) == 0.0
    assert sp.accumulate([{}]) == 0.0
    assert sp.accumulate(['not-a-dict']) == 0.0


def test_level_from_score_tolerates_garbage():
    assert sp.level_from_score(None) == 0
    assert sp.level_from_score('abc') == 0


def test_accumulated_capped():
    """累计有上限，防止展示出天文数字。"""
    score = sp.accumulate([{'score': 100, 'age_days': 0}] * 100000)
    assert score <= sp.MAX_ACCUMULATED
