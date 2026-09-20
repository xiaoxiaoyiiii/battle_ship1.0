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


def test_same_ip_avoided_when_alternative_exists():
    """同 IP 的两个人，在有别人可选时会被避开（用公网 IP）。"""
    a = C('s1', uid='u1', ip='203.0.113.9')
    b = C('s2', uid='u2', ip='203.0.113.9')     # 与 a 同 IP
    c = C('s3', uid='u3', ip='198.51.100.7')
    q = [a, b, c]
    i, j, clean = mg.pick_pair(q)
    picked = {q[i].sid, q[j].sid}
    assert picked != {'s1', 's2'}, '应当避开同 IP 的一对'


def test_dirty_same_ip_is_hard_blocked():
    """同一 IP 且该 IP 两个账号都脏 → 硬拦（刷分机房的典型特征）。"""
    a = C('s1', uid='u1', ip='203.0.113.9', ip_dirty=True)
    b = C('s2', uid='u2', ip='203.0.113.9', ip_dirty=True)
    assert mg.hard_block(a, b) == 'same_ip_dirty'


def test_dirty_same_ip_not_rescued_by_fallback():
    """硬拦的对**永远不许**被兜底救回来 —— 否则等于没拦。"""
    q = [C('s1', uid='u1', ip='203.0.113.9', ip_dirty=True),
         C('s2', uid='u2', ip='203.0.113.9', ip_dirty=True)]
    i, j, clean = mg.pick_pair(q)
    assert i is None and j is None, '脏 IP 自配不该被兜底放行'


def test_one_side_dirty_same_ip_not_hard_blocked():
    """只有一方脏 → 不硬拦（脏的人也可能在网吧/校园网）。"""
    a = C('s1', uid='u1', ip='203.0.113.9', ip_dirty=True)
    b = C('s2', uid='u2', ip='203.0.113.9', ip_dirty=False)
    assert mg.hard_block(a, b) == ''


# ===========================================================================
# B0. ★ 回环 / 内网地址 —— 实测事故的守卫（本文件最重要的一组）
# ===========================================================================
def test_loopback_ip_treated_as_no_ip():
    """★ 回环地址一律当"没有 IP"。

    事故：同 IP 软规避一作用于 `127.0.0.1`，本机跑测试时**所有**配对都被降权
    → 兜底 → `room.ranked=False` → 排位分**静默全部不结算**
    （页面照常开局、接口照常返回、零报错，只有分数不动）。
    """
    a = C('s1', uid='u1', ip='127.0.0.1')
    b = C('s2', uid='u2', ip='127.0.0.1')
    assert a.ip == '' and b.ip == '', '回环地址必须被归一成空'
    i, j, clean = mg.pick_pair([a, b])
    assert clean is True, '回环 IP 的两人必须被判成"干净对"（否则排位会被悄悄关掉）'


def test_private_and_loopback_variants_are_ignored():
    """内网 / 链路本地 / IPv4-mapped 等各种写法都要被识别为"不可用"。"""
    for ip in ('127.0.0.1', '127.1.2.3', 'localhost', '::1', '0.0.0.0',
               '10.0.0.5', '192.168.1.7', '169.254.1.1',
               '172.16.0.1', '172.31.255.255', 'fe80::1', 'fd00::1', 'fc00::1',
               '::ffff:127.0.0.1'):
        assert mg._usable_ip(ip) == '', f'{ip} 应当被视为不可用'


def test_public_ip_is_usable():
    """公网地址正常参与判定。"""
    for ip in ('8.8.8.8', '203.0.113.9', '2001:db8::1'):
        assert mg._usable_ip(ip) == ip


def test_public_172_is_usable():
    """172.x 只有 16~31 段才是私有，其它段是公网。"""
    assert mg._usable_ip('172.15.0.1') == '172.15.0.1'
    assert mg._usable_ip('172.32.0.1') == '172.32.0.1'
    assert mg._usable_ip('172.16.0.1') == ''


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


def test_recent_opponents_still_match_when_alone():
    """★ 只有刚打过的两人排队 → 仍然配上（偏好上非最优）。"""
    a = C('s1', uid='u1', ip='1.1.1.1', recent_foes=('u2',))
    b = C('s2', uid='u2', ip='2.2.2.2', recent_foes=('u1',))
    q = [a, b]
    i, j, clean = mg.pick_pair(q)
    assert i is not None and j is not None
    assert clean is False


def test_fallback_still_earns_ranked():
    """★★ 回归守卫：**兜底配出来的对，排位分照常结算**。

    本项目栽过（2026-09-20，玩家实测报"排位分都不加/不扣了"）：
    `server.py` 曾用 `and bool(assessed)` 把"兜底配对"直接变成 `room.ranked=False`，
    于是小社区里最常见的「和刚打过的人再打一局」**全部静默不结算**。

    根因：把**配对偏好**（`assessed`）当成了**结算判据**。
    "给不给分"取决于**对局内容**，由 `anticheat` 判据负责 —— 那条路与本模块无关。

    ⚠️ 这条断言必须走**真实配对代码**（`server.handle_find_match`），
       只测 `match_guard` 纯函数是拦不住这个 bug 的
       （bug 在"拿 assessed 去关排位"那一步上）。见
       `tests/test_ranked_match.py::test_rematch_pairing_still_settles_ranked`。
    """
    # `should_settle_ranked` 这个函数已被删除：它编码的正是那个错误政策。
    assert not hasattr(mg, 'should_settle_ranked'), \
        '不该再有"按配对偏好决定是否结算排位"的接口 —— 那是把两件事混成一件'


def test_empty_and_single_queue():
    """空队列 / 只有一个人 → 配不出来，且不许抛。"""
    assert mg.pick_pair([]) == (None, None, False)
    assert mg.pick_pair([C('s1', uid='u1')]) == (None, None, False)


def test_no_infinite_loop_on_unsatisfiable_queue():
    """排位队列被休闲挡着 → 返回"配不出"，由调用方 break（不许死循环）。"""
    q = [C('s1', uid='u1', mode='ranked'), C('s2', uid='u2', mode='casual')]
    i, j, clean = mg.pick_pair(q)
    assert i is None and j is None


# ===========================================================================
# C. 干净对：正常情况不许被误伤
# ===========================================================================
def test_clean_pair_is_clean():
    """两个不同 IP、没交手过的人 → 干净对，正常结算。"""
    a = C('s1', uid='u1', ip='1.1.1.1')
    b = C('s2', uid='u2', ip='2.2.2.2')
    i, j, clean = mg.pick_pair([a, b])
    assert (i, j) == (0, 1)
    assert clean is True


def test_guests_without_ip_still_pair():
    """游客没有 uid / 没有 ip → 不许被当成"同 IP"误伤。"""
    a = C('s1', uid=None, ip='')
    b = C('s2', uid=None, ip='')
    i, j, clean = mg.pick_pair([a, b])
    assert i is not None and j is not None
    assert clean is True


def test_old_opponent_is_not_recent():
    """很久以前交手过的人不在 recent_foes 里 → 不降权（口径由调用方保证）。"""
    a = C('s1', uid='u1', ip='1.1.1.1', recent_foes=())
    b = C('s2', uid='u2', ip='2.2.2.2')
    assert mg.pair_score(a, b) == mg.SCORE_BASE
    i, j, clean = mg.pick_pair([a, b])
    assert clean is True


def test_waiting_player_gets_priority():
    """等得久的人应当优先被配上（避免被反复让位而一直排不上）。"""
    fresh = C('s1', uid='u1', ip='1.1.1.1')
    waiting = C('s2', uid='u2', ip='2.2.2.2', waited=600)
    other = C('s3', uid='u3', ip='3.3.3.3')
    assert mg.pair_score(waiting, other) > mg.pair_score(fresh, other)


# ===========================================================================
# D. 健壮性
# ===========================================================================
def test_deterministic():
    q = [C('s1', uid='u1', ip='1.1.1.1'), C('s2', uid='u2', ip='2.2.2.2')]
    assert mg.pick_pair(q) == mg.pick_pair(q)


def test_returns_valid_indices():
    q = [C('s1', uid='u1'), C('s2', uid='u2'), C('s3', uid='u3')]
    i, j, _ = mg.pick_pair(q)
    assert 0 <= i < j < len(q)


def test_candidate_tolerates_garbage():
    """脏输入不许抛（失败开放）。"""
    a = mg.Candidate('s1', uid=None, mode=None, ip=None, recent_foes=None)
    b = mg.Candidate('s2', uid=None, mode=None, ip=None)
    mg.pick_pair([a, b])
    mg.hard_block(a, b)
    mg.pair_score(a, b)
