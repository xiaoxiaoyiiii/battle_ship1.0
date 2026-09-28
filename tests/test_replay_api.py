# -*- coding: utf-8 -*-
"""对局回放批 · 接口层（`api.py`）：三个新接口 + `/user_stats` 的 `has_replay`。

契约见 `docs/REPLAY_2026_09_23.md` §5（权限与隐私）、§6（后端接口）、
§8 的 5（鉴权三情形双向）/ 6（开关语义）/ 10（字节上限）。

## 鉴权判据（§5）

`GET /api/replay/<match_id>` 放行当且仅当：

* 请求者是**该局参与者**（`winner_user_id` / `loser_user_id` == 自己），**或**
* 该局某个真实参与者 `show_history = 1`（实测默认 **0 = 不公开** ⇒ 默认只有双方能看到）。

## 三条"必须双向断言"的理由（教训 #12）

隐私过滤**只有服务端拦得住**：前端断言会假绿（前端看到开关就提前 return、压根不拉数据）。
所以这里的每一条权限用例都**以别人的身份直读接口**，而且**两侧都断言**
（该放行的必须 200、该拒的必须 403）—— 只测"拒了"会在接口整个坏掉时照样通过。
"""
import json
import uuid

import pytest

import db as db_module
import replay as replay_module
import server


def _account():
    uid = db_module.create_user('rep-%s' % uuid.uuid4().hex[:10], 'x' * 12)
    assert uid, '建测试账号失败'
    return uid


def _http(uid=None, username=None):
    """真登录态的 HTTP 客户端（与观战批同一套）。"""
    http = server.app.test_client()
    if uid:
        with http.session_transaction() as sess:
            sess['user_id'] = uid
            sess['username'] = username or uid
    return http


def _make_replay(winner_uid, loser_uid, steps=4, step_seconds=None, **kw):
    """走**真实入口** `db.record_match(..., replay=...)` 造一局带回放的对局。"""
    blob = {
        'version': replay_module.REPLAY_VERSION,
        'p1_name': '甲',
        'p2_name': '乙',
        'started_at': 1_700_000_000,
        'steps': [{'i': i, 'kind': 'attack', 'actor': '甲', 'text': '第%d步' % i,
                   'detail': {'attacker': 'sid-a', 'target': {'x': i, 'y': 0},
                              'hit': True, 'ship_sunk': False}} for i in range(steps)],
        'ships': [{'step': 0, 'p1': [{'x': 0, 'y': 0, 'alive': True}],
                   'p2': [{'x': 0, 'y': 5, 'alive': True}]}],
        'hands': [{'step': 0, 'p1': ['失灵！'], 'p2': []}],
        'board_resets': [{'step': 2, 'side': 'p1'}],
        'nodes': [{'step': 1, 'kind': 'hit', 'label': '命中 (1,0)'}],
        'truncated': None,
    }
    blob.update(kw)
    ok = db_module.record_match(winner_uid or 'guest-w', loser_uid or 'guest-l',
                                logs=[{'text': 'x'}], replay=blob,
                                replay_participants={'winner': winner_uid,
                                                     'loser': loser_uid})
    assert ok
    mid = db_module.db.cursor.execute(
        'SELECT id FROM matches ORDER BY rowid DESC LIMIT 1').fetchone()['id']
    return mid


# ===========================================================================
# §8-5 鉴权三情形**双向**
# ===========================================================================
def test_participant_can_read_and_gets_you_are():
    """★ 情形①：参与者能看，且拿到 `you_are`（`p1` 胜者 / `p2` 败者）。"""
    w, l = _account(), _account()
    mid = _make_replay(w, l)

    resp = _http(w).get('/api/replay/%s' % mid)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body['success'] is True
    assert body['you_are'] == 'p1'
    assert body['replay']['steps'][0]['i'] == 0
    # ★ 绝不下发任何 user_id（契约 §6）
    dumped = json.dumps(body, ensure_ascii=False)
    assert w not in dumped and l not in dumped, '响应里带出了 user_id'

    loser_view = _http(l).get('/api/replay/%s' % mid).get_json()
    assert loser_view['you_are'] == 'p2', '败者应当是 p2'


def test_stranger_is_rejected_when_history_is_private():
    """★ 情形②：非参与者 + `show_history=0`（**默认**）⇒ 拒（403）。

    反向腿同时在：同一条回放、同一个接口，**参与者**必须拿得到 200 ——
    否则"拒了"可能只是因为整个接口坏了（空转绿）。
    """
    w, l, stranger = _account(), _account(), _account()
    mid = _make_replay(w, l)
    # 默认就是 0（不公开）；显式写一遍，免得将来默认值漂移让这条悄悄失去意义
    db_module.save_user_profile_extra(w, {'show_history': 0})
    db_module.save_user_profile_extra(l, {'show_history': 0})

    denied = _http(stranger).get('/api/replay/%s' % mid)
    assert denied.status_code == 403, denied.get_data(as_text=True)
    assert denied.get_json()['success'] is False
    assert '权限' in denied.get_json()['error']
    # 反向腿
    assert _http(w).get('/api/replay/%s' % mid).status_code == 200


def test_stranger_can_read_when_one_side_publishes_history():
    """★ 情形③：非参与者 + 有任一方 `show_history=1` ⇒ **放行**。

    这条也保护"另一侧"：另一个参与者仍然关着历史，但**任一方**公开就够
    （契约 §5 的原话："该局某个真实参与者 show_history = 1"）。
    """
    w, l, stranger = _account(), _account(), _account()
    mid = _make_replay(w, l)
    db_module.save_user_profile_extra(w, {'show_history': 1})
    db_module.save_user_profile_extra(l, {'show_history': 0})

    resp = _http(stranger).get('/api/replay/%s' % mid)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body['you_are'] is None, '旁观者不该被算成某一位'
    assert body['replay']['version'] == replay_module.REPLAY_VERSION


def test_anonymous_is_rejected():
    """★ 假设 A1：回放接口**要求登录**（游客 401）。"""
    w, l = _account(), _account()
    mid = _make_replay(w, l)
    db_module.save_user_profile_extra(w, {'show_history': 1})
    resp = _http().get('/api/replay/%s' % mid)
    assert resp.status_code == 401, resp.get_data(as_text=True)
    assert '未登录' in resp.get_json()['error']


def test_missing_replay_is_404_with_a_reason():
    """★ 没有这条回放 ⇒ 404 且**带原因**（不是静默空对象，教训 #32）。"""
    uid = _account()
    resp = _http(uid).get('/api/replay/%s' % uuid.uuid4())
    assert resp.status_code == 404, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body['success'] is False and body['error']


# ===========================================================================
# §8-6 开关语义
# ===========================================================================
def test_setting_round_trip_and_validation():
    """★ `GET`/`POST /api/replay/setting`：默认开、能关、非布尔 400、未登录 401。"""
    uid = _account()
    http = _http(uid)
    got = http.get('/api/replay/setting')
    assert got.status_code == 200
    assert got.get_json() == {'success': True, 'allow_replay': True}, '默认必须是开'

    off = http.post('/api/replay/setting', json={'allow_replay': False})
    assert off.status_code == 200 and off.get_json()['allow_replay'] is False
    assert http.get('/api/replay/setting').get_json()['allow_replay'] is False

    on = http.post('/api/replay/setting', json={'allow_replay': True})
    assert on.status_code == 200 and on.get_json()['allow_replay'] is True

    bad = http.post('/api/replay/setting', json={'allow_replay': 'maybe'})
    assert bad.status_code == 400, bad.get_data(as_text=True)
    missing = http.post('/api/replay/setting', json={})
    assert missing.status_code == 400
    assert _http().post('/api/replay/setting', json={'allow_replay': True}).status_code == 401


def test_setting_get_reports_unknown_instead_of_lying():
    """★ 读库失败 ⇒ **503 如实说不知道**，绝不许谎报成"允许"（教训 #21）。"""
    uid = _account()
    http = _http(uid)
    real = db_module.db.get_allow_replay
    db_module.db.get_allow_replay = lambda who: None
    try:
        resp = http.get('/api/replay/setting')
        assert resp.status_code == 503, resp.get_data(as_text=True)
        assert resp.get_json()['success'] is False
    finally:
        db_module.db.get_allow_replay = real


# ===========================================================================
# §8-10 字节上限（**拒收 + 明确报错**，不是静默空）
# ===========================================================================
def _force_blob_size(match_id, size, valid_json=True):
    """把某条回放的 blob **和** `bytes` 列一起改成指定大小（模拟坏 blob）。"""
    if valid_json:
        blob = json.dumps({'version': replay_module.REPLAY_VERSION,
                           'pad': 'x' * max(0, size - 40)})
    else:
        blob = 'x' * size
    db_module.db.cursor.execute(
        'UPDATE match_replays SET replay = ?, bytes = ? WHERE match_id = ?',
        (blob, len(blob.encode('utf-8')), match_id))
    db_module.db.conn.commit()
    return len(blob.encode('utf-8'))


def _force_bytes_column(match_id, size):
    """只改 `bytes` 列（blob 本身不动）—— 用来**单独**测第一道闸。"""
    db_module.db.cursor.execute(
        'UPDATE match_replays SET bytes = ? WHERE match_id = ?', (size, match_id))
    db_module.db.conn.commit()


def test_oversized_bytes_column_is_rejected_with_a_reason_and_logged(capsys):
    """★★ §8-10：`bytes` 列超限 ⇒ **拒收 + 明确报错 + 打日志**（绝不静默）。

    ⚠️ 这里**只把 `bytes` 列改大**、blob 保持很小 —— 于是第二道闸（按真实字节）
       不会介入，这条用例测的就是第一道闸**自己**在拦（两道闸各有一条独立的用例，
       否则"改坏其中一道"时另一道会替它兜住，那条守卫就是绿着的摆设）。
    """
    w, l = _account(), _account()
    mid = _make_replay(w, l)
    _force_bytes_column(mid, replay_module.MAX_REPLAY_BYTES + 5000)
    row = db_module.db.get_match_replay(mid)
    assert int(row['bytes']) > replay_module.MAX_REPLAY_BYTES
    assert len(row['replay'].encode('utf-8')) < 1024, '前置：blob 本身必须很小'

    resp = _http(w).get('/api/replay/%s' % mid)
    assert resp.status_code == 500, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body['success'] is False
    assert 'replay' not in body, '超限时**不许**返回半份数据'
    assert '超限' in body['error'], body['error']
    assert '[replay]' in capsys.readouterr().out, '超限必须打日志（不许静默）'


def test_blob_over_limit_by_actual_bytes_is_also_rejected():
    """★ 第二道闸：`bytes` 列**小**、真实字节**超限** ⇒ 也要拒（500）。

    ⚠️ 必须让第一道闸看到一个小值，否则它先拦掉，这条就测不到第二道 ——
       实测踩过：只改坏第二道时它仍然是绿的。
    """
    w, l = _account(), _account()
    mid = _make_replay(w, l)
    _force_blob_size(mid, replay_module.MAX_REPLAY_BYTES + 5000)
    _force_bytes_column(mid, 10)
    row = db_module.db.get_match_replay(mid)
    assert int(row['bytes']) == 10, '前置：`bytes` 列必须是小的那个'
    assert len(row['replay'].encode('utf-8')) > replay_module.MAX_REPLAY_BYTES

    resp = _http(w).get('/api/replay/%s' % mid)
    assert resp.status_code == 500, resp.get_data(as_text=True)
    assert '超限' in resp.get_json()['error']


def test_broken_blob_is_reported_and_deleted(capsys):
    """★★ §6 / §9：解析失败 ⇒ **明确报错 + 打日志 + 顺手删掉这条坏回放**。

    绝不静默返回空（教训 #32），也绝不把坏数据一直留着（每次点都炸一次）。
    """
    w, l = _account(), _account()
    mid = _make_replay(w, l)
    _force_blob_size(mid, 100, valid_json=False)

    resp = _http(w).get('/api/replay/%s' % mid)
    assert resp.status_code == 500, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body['success'] is False and '损坏' in body['error']
    log = capsys.readouterr().out
    assert '[replay]' in log, '解析失败必须打日志（不许静默）'
    assert db_module.db.get_match_replay(mid) is None, '坏回放没被删掉'


def test_unknown_version_is_rejected_but_kept():
    """★ 版本对不上 ⇒ 明确报错（**不删**：将来可能有人读得懂旧版本）。"""
    w, l = _account(), _account()
    mid = _make_replay(w, l, version=replay_module.REPLAY_VERSION + 99)
    resp = _http(w).get('/api/replay/%s' % mid)
    assert resp.status_code == 409, resp.get_data(as_text=True)
    assert '版本' in resp.get_json()['error']
    assert db_module.db.get_match_replay(mid) is not None, '版本不认识不该删数据'


# ===========================================================================
# §8-4 `/user_stats` 不含回放 blob
# ===========================================================================
def test_user_stats_history_has_has_replay_and_no_blob():
    """★★ §8-4：30 局历史的响应字节数必须在上限内，且**一个字节的 blob 都没有**。"""
    uid = _account()
    ids = [_make_replay(uid, _account(), steps=6) for _ in range(6)]
    resp = _http(uid).get('/user_stats?limit=30')
    assert resp.status_code == 200
    body = resp.get_json()
    history = body['history']
    assert len(history) == 6, len(history)
    for row in history:
        assert row['has_replay'] is True
        assert 'replay' not in row and 'ships' not in row and 'steps' not in row
    raw = resp.get_data(as_text=True)
    assert 'board_resets' not in raw, '战绩接口带出了回放内容'
    assert len(raw.encode('utf-8')) < 20000, '响应被回放撑大了：%d 字节' % len(raw.encode('utf-8'))
    assert set(ids) <= {row['match_id'] for row in history}


def test_user_stats_reports_null_mode_without_substituting(tmp_path):
    """★ 老数据（`matches.mode` 为 NULL）必须**原样给 None**，不许兜底成 'casual'。

    这是教训 #21 的形状：老数据是"不知道"，伪装成"匹配"就是错的。
    """
    uid = _account()
    db_module.record_match(uid, _account(), logs=[{'text': 'x'}])
    mid = db_module.db.cursor.execute(
        'SELECT id FROM matches ORDER BY rowid DESC LIMIT 1').fetchone()['id']
    db_module.db.cursor.execute('UPDATE matches SET mode = NULL WHERE id = ?', (mid,))
    db_module.db.conn.commit()
    row = [h for h in _http(uid).get('/user_stats').get_json()['history']
           if h['match_id'] == mid][0]
    assert 'mode' in row, 'history 每行都要有 mode 键（老数据也要有，值为 None）'
    assert row['mode'] is None, 'NULL 被兜底成了 %r' % row['mode']
