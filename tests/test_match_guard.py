# -*- coding: utf-8 -*-
"""匹配规避单测（`match_guard.py`）。

两条主线，缺一不可：
  A. **规避有效**：同 IP / 近来交手过的对手，在有更好选择时会被避开；
  B. ★ **绝不卡死**：队列里只有"该被规避"的两个人时，**仍然要能配上**
     —— 否则深夜两个同宿舍的人永远开不了局，比刷分更伤正常玩家。

外加一组**回环/内网地址**的守卫：这是实测撞出来的事故 ——
同 IP 规避一作用于 `127.0.0.1`，本机所有配对都被降权 → 兜底 →
`room.ranked=False` → **排位分静默全部不结算**（页面照常开局、零报错）。
"""
import match_guard as mg


def C(sid, uid=None, mode='casual', ip='', recent_foes=(), ip_dirty=False, waited=0):
    return mg.Candidate(sid, uid=uid, mode=mode, ip=ip,
                        recent_foes=recent_foes, ip_dirty=ip_dirty,
                        waited_sec=waited)


# ===========================================================================
# A. 规避有效
# ===========================================================================
def test_same_account_never_paired():
    """同一账号的两个标签页 —— 既有行为，硬拦。"""
    a = C('s1', uid='u1', ip='1.1.1.1')
    b = C('s2', uid='u1', ip='1.1.1.1')
    assert mg.hard_block(a, b) == 'same_account'


def test_different_modes_never_paired():
    """休闲与排位不混配（既有行为）。"""
    q = [C('s1', uid='u1', mode='casual'), C('s2', uid='u2', mode='ranked')]
    i, j, clean = mg.pick_pair(q)
    assert i is None and j is None


def test_recent_opponent_avoided_when_third_player_available():
    """近来交手过的人会被避开 —— 优先配那个没打过的。"""
    a = C('s1', uid='u1', ip='1.1.1.1', recent_foes=('u2',))
    b = C('s2', uid='u2', ip='2.2.2.2', recent_foes=('u1',))
    c = C('s3', uid='u3', ip='3.3.3.3')
    q = [a, b, c]
    i, j, clean = mg.pick_pair(q)
    picked = {q[i].sid, q[j].sid}
    assert 's3' in picked, f'应当优先配新对手，实际配了 {picked}'
    assert clean is True




def test_dirty_same_ip_is_hard_blocked():
    """同一 IP 且该 IP 两个账号都脏 → 硬拦（刷分机房的典型特征）。"""
    a = C('s1', uid='u1', ip='203.0.113.9', ip_dirty=True)
    b = C('s2', uid='u2', ip='203.0.113.9', ip_dirty=True)
    assert mg.hard_block(a, b) == 'same_ip_dirty'






# ===========================================================================
# B0. ★ 回环 / 内网地址 —— 实测事故的守卫（本文件最重要的一组）
# ===========================================================================








# ===========================================================================
# B. ★ 绝不卡死
# ===========================================================================
def test_same_public_ip_pair_still_matches_when_alone():
    """公网同 IP 的两个人单独排队 → 仍然配上。

    ⚠️ `clean=False` 只表示"偏好上不是最优"，**不代表不给分**
    （见 `test_fallback_still_earns_ranked` 那条回归守卫）。
    """
    a = C('s1', uid='u1', ip='203.0.113.9')
    b = C('s2', uid='u2', ip='203.0.113.9')
    q = [a, b]
    i, j, clean = mg.pick_pair(q)
    assert i is not None and j is not None, '同 IP 两人必须仍能配上（绝不卡死）'
    assert clean is False, '同 IP 在偏好上算"非最优"'








def test_no_infinite_loop_on_unsatisfiable_queue():
    """排位队列被休闲挡着 → 返回"配不出"，由调用方 break（不许死循环）。"""
    q = [C('s1', uid='u1', mode='ranked'), C('s2', uid='u2', mode='casual')]
    i, j, clean = mg.pick_pair(q)
    assert i is None and j is None


# ===========================================================================
# C. 干净对：正常情况不许被误伤
# ===========================================================================








# ===========================================================================
# D. 健壮性
# ===========================================================================
