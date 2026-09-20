# -*- coding: utf-8 -*-
"""反作弊闸门的**端到端**测试（2026-09-19）。

分两层：
  A. 纯判据层已在 `tests/test_anticheat.py`（26 条）；
  B. **本文件**验证"判据接进服务端之后真的拦得住"—— 只测纯函数是不够的，
     本项目栽过「解锁逻辑看着有、其实永远不触发，而接口/前端/测试全都不报错」
     （CLAUDE.md §10.13）。所以这里走**真实 `_finalize_match`**，断言分数确实没动。

⚠️ 账号一律带 `_TAG` 前缀并在结束时清掉 `user_rank` 行 ——
   船长池是全库共享的，留垃圾会污染其它用例（与 `test_rank_points.py` 同规矩）。
"""
import itertools

import pytest

import db
import server

_seq = itertools.count(1)
_TAG = 'ac9'


def _mk_user():
    name = f'{_TAG}{next(_seq)}'
    uid = db.create_user(name, 'x' * 12)
    assert uid, f'建号失败: {name}'
    return uid


def _purge(uids):
    try:
        with db.db._lock:
            for uid in uids:
                if not uid:
                    continue
                for table in ('user_rank', 'user_xp', 'user_counters',
                              'user_achievements', 'anticheat_flags'):
                    try:
                        if table == 'anticheat_flags':
                            continue
                        db.db.conn.execute(
                            f'DELETE FROM {table} WHERE user_id = ?', (uid,))
                    except Exception:
                        pass
            db.db.conn.commit()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _clean_globals():
    existing = set(server.room_manager.get_all_rooms())
    server.room_manager.match_queue = []
    yield
    for rid in list(server.room_manager.get_all_rooms()):
        if rid not in existing:
            server.room_manager.rooms.pop(rid, None)
    server.room_manager.match_queue = []


# ---------------------------------------------------------------------------
# 一、`_anticheat_facts` 从房间对象取事实（纯组装，不碰判据）
# ---------------------------------------------------------------------------
def _mk_room(rounds=1, a_hits=6, b_hits=0, b_ships=6):
    """造一个最小房间：甲打中乙 a_hits 格、乙打中甲 b_hits 格。

    ⚠️ 构造签名照真实类来（`PlayerShip(positions, hits)`、`Player(name, ships, attacks, remaining_ships, ...)`），
    不要凭记忆写 —— 期望式构造会让测试红在自己身上而不是被测代码上。
    """
    from server import GameRoom, Player, PlayerShip, Position

    room = GameRoom('ac-room')
    room.round = rounds

    # 甲的 1 艘船：被乙打中 b_hits 格
    sa = PlayerShip([Position(0, 5)], [Position(0, 5)] * b_hits)
    pa = Player('甲', [sa], [], 1, user_id='ua')

    # 乙的 b_ships 艘船：前 a_hits 艘被甲打中（每艘 1 格）
    sb = []
    for i in range(b_ships):
        pos = [Position(i, 0)]
        sb.append(PlayerShip(pos, list(pos) if i < a_hits else []))
    pb = Player('乙', sb, [], b_ships, user_id='ub')

    room.players = {'pa': pa, 'pb': pb}
    return room


def test_facts_extracts_hits_without_id_alignment():
    """事实提取只看命中格子数，不依赖 user_id / socket sid 对齐。"""
    room = _mk_room(rounds=1, a_hits=6, b_hits=0, b_ships=6)
    f = server._anticheat_facts(room, 'pa', 'pb')
    assert f['rounds'] == 1
    assert f['max_hits'] == 6
    assert f['foe_ships'] == 6
    assert len(f['attackers']) == 1          # 只有一方打中过


def test_facts_is_exception_safe():
    """房间对象残缺也不许抛（失败开放）。"""
    f = server._anticheat_facts(object(), 'x', 'y')
    assert isinstance(f, dict)


# ---------------------------------------------------------------------------
# 二、★ 核心：被判定的对局**拿不到排位分**
# ---------------------------------------------------------------------------
def test_blocked_match_gives_no_rank_points(monkeypatch):
    """判据判定 block → `_finalize_match` 必须**不给分**。

    这是"让刷分不再有收益"的落点。打桩判据返回 block，
    验证闸门真的接上了（而不是只写了个不会被调用的函数）。
    """
    ua, ub = _mk_user(), _mk_user()
    room = _mk_room()
    room.ranked = True
    try:
        db.set_rank_points(ua, 100)
        db.set_rank_points(ub, 100)

        # 让双方都是登录用户，且已经"真开打"
        room.players['pa'].user_id = ua
        room.players['pb'].user_id = ub
        monkeypatch.setattr(server, '_match_really_started', lambda r: True)
        monkeypatch.setattr(server, '_count_stats_for', lambda r: True)
        # ★ 判据打桩成 block
        monkeypatch.setattr(server, '_anticheat_assess',
                            lambda r, w, l: {'score': 100, 'level': 'block',
                                             'reasons': [], 'rules': ['sweep_perfect_win'],
                                             'blocked': True})

        server._finalize_match(room, 'pa', 'pb')

        assert db.get_user_rank_row(ua)['points'] == 100, '被判定刷分的胜者不该加分'
        assert db.get_user_rank_row(ub)['points'] == 100, '被判定刷分的败者不该扣分'
    finally:
        _purge([ua, ub])


def test_clean_match_still_settles(monkeypatch):
    """反向守卫：判据返回 clean 时**必须照常结算** —— 闸门不能把所有局都拦掉。"""
    ua, ub = _mk_user(), _mk_user()
    room = _mk_room()
    room.ranked = True
    try:
        db.set_rank_points(ua, 100)
        db.set_rank_points(ub, 100)
        room.players['pa'].user_id = ua
        room.players['pb'].user_id = ub
        monkeypatch.setattr(server, '_match_really_started', lambda r: True)
        monkeypatch.setattr(server, '_count_stats_for', lambda r: True)
        monkeypatch.setattr(server, '_anticheat_assess',
                            lambda r, w, l: {'score': 0, 'level': 'clean',
                                             'reasons': [], 'rules': [],
                                             'blocked': False})

        server._finalize_match(room, 'pa', 'pb')

        assert db.get_user_rank_row(ua)['points'] > 100, '正常对局必须照常加分'
    finally:
        _purge([ua, ub])


def test_assess_failure_does_not_block(monkeypatch):
    """判据炸了 → 失败开放，照常结算（反作弊绝不许把对局结算搞崩）。"""
    ua, ub = _mk_user(), _mk_user()
    room = _mk_room()
    room.ranked = True
    try:
        db.set_rank_points(ua, 100)
        db.set_rank_points(ub, 100)
        room.players['pa'].user_id = ua
        room.players['pb'].user_id = ub
        monkeypatch.setattr(server, '_match_really_started', lambda r: True)
        monkeypatch.setattr(server, '_count_stats_for', lambda r: True)

        def _boom(*a, **k):
            raise RuntimeError('判据崩了')

        monkeypatch.setattr(server, 'anticheat', type('X', (), {
            'evaluate': staticmethod(_boom), 'explain': staticmethod(lambda r: '')}))

        server._finalize_match(room, 'pa', 'pb')
        assert db.get_user_rank_row(ua)['points'] > 100, '判据异常时必须放行正常结算'
    finally:
        _purge([ua, ub])


# ---------------------------------------------------------------------------
# 三、真实形态：引擎在真实房间对象上抓得到「人肉靶子」
# ---------------------------------------------------------------------------
def test_real_shape_is_blocked_by_engine():
    """用真实房间形状（单方第 1 回合全歼、另一方零命中）走真判据 → 必须 block。"""
    room = _mk_room(rounds=1, a_hits=6, b_hits=0, b_ships=6)
    res = server._anticheat_assess(room, 'pa', 'pb')
    assert res['blocked'] is True, f'真实靶子形态没被拦住: {res}'
    assert 'sweep_perfect_win' in res['rules']


def test_normal_shape_not_blocked_by_engine():
    """正常对局（双方都有命中、打了 10 回合）→ 不拦。"""
    room = _mk_room(rounds=10, a_hits=6, b_hits=4, b_ships=6)
    res = server._anticheat_assess(room, 'pa', 'pb')
    assert res['blocked'] is False, f'正常对局被误拦: {res}'


# ---------------------------------------------------------------------------
# 四、审计：判定结果要落库（可复查）
# ---------------------------------------------------------------------------
def test_report_records_flag():
    room = _mk_room()
    room.id = 'ac-report-room'
    res = {'score': 100, 'level': 'block', 'rules': ['sweep_perfect_win'],
           'reasons': [], 'blocked': True}
    server._anticheat_report(room, 'pa', 'pb', res)
    rows = [r for r in db.get_anticheat_flags(50) if r['match_id'] == 'ac-report-room']
    assert rows, '判定结果必须落库，否则事后无法复查'
    assert rows[0]['severity'] == 'block'
    # 清理
    try:
        with db.db._lock:
            db.db.conn.execute('DELETE FROM anticheat_flags WHERE match_id=?',
                               ('ac-report-room',))
            db.db.conn.commit()
    except Exception:
        pass


def test_report_clean_writes_nothing():
    room = _mk_room()
    room.id = 'ac-clean-room'
    server._anticheat_report(room, 'pa', 'pb',
                             {'score': 0, 'level': 'clean', 'rules': [],
                              'reasons': [], 'blocked': False})
    rows = [r for r in db.get_anticheat_flags(50) if r['match_id'] == 'ac-clean-room']
    assert not rows, '干净对局不该写审计记录（否则表会被正常对局淹没）'
