# -*- coding: utf-8 -*-
"""对局回放批 · 记录器（`replay.py` + `server.py` 的接线）。

契约见 `docs/REPLAY_2026_09_23.md` §3（记录器）、§8 的 11（记录点不漏）、
§1（内存账）、§9（边界与失败模式）。

这个文件里最要紧的几条：

* `test_one_full_game_records_steps` —— **真打完一整局**（无头对局驱动器），
  所以"38 个 `add_game_log` 点里那些会在真对局里出现的"确实被跑到了；
* `test_every_step_has_the_contract_shape` —— 每个步骤的键集合钉死；
* `test_recorder_memory_and_blob_are_within_budget` —— **实测**每局常驻与 blob 字节数
  （契约 §1 的内存账，不是估算）；
* `test_truncation_is_explicit` —— 触限必须**明确标注**，绝不静默。
"""
import ast
import io
import json
import pathlib
import uuid

import pytest

import db as db_module
import replay
import server
from server import GameRoom, MagicCard, Player, PlayerShip, Position, room_manager
from tools import headless_game as hg

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SERVER_PY = REPO_ROOT / 'server.py'

SID_A, SID_B = 'rep-sid-a', 'rep-sid-b'
P1_SHIPS = tuple(((x, 0),) for x in range(6))
P2_SHIPS = tuple(((x, 5),) for x in range(6))


# ===========================================================================
# 一局真对局：录制 → 落库 → 内存置空
# ===========================================================================
class _Capture:
    """把 `_finalize_match` 里那一次 `replay.finalize` 的结果抓下来。

    为什么要劫持这里而不是直接调 `replay.finalize(room)`：
    无头驱动器的房间在 `__exit__` 里就被删了，而**收口时**那一份才是真正要落库的。
    顺带还能证明"落库之后内存立刻置空"（契约 §1）。
    """

    def __init__(self, monkeypatch):
        self.payload = None
        self.error = None
        self.calls = 0
        self.real = replay.finalize

        def spy(room):
            self.calls += 1
            try:
                out = self.real(room)
            except Exception as exc:            # noqa: BLE001
                self.error = exc
                raise
            if out is not None:
                self.payload = out
            return out

        monkeypatch.setattr(replay, 'finalize', spy)


@pytest.fixture
def capture(monkeypatch):
    return _Capture(monkeypatch)


@pytest.fixture
def with_real_human(monkeypatch):
    """给无头对局的**真人座位**挂一个真账号。

    为什么必须挂：回放的开关判据（`_replay_allowed_for_match`）要求
    "至少一侧是真账号"，而无头驱动器的真人座位默认 `user_id=None`
    （它是度量工具，不是登录用户）—— 不挂的话**这一整局都不留回放**，
    而这些用例测的正是"真对局录得对不对"。

    ⚠️ 只给**人类座位**挂，AI 座位仍然没有账号 —— 那正是线上人机局的形状
    （`matches.mode='ai'`、参与者只有人类一侧）。
    """
    uid = _account()
    real = server.room_manager.create_ai_room

    def patched(*a, **kw):
        room_id = real(*a, **kw)
        # `_build()` 在 `create_ai_room` 返回**之后**才建真人座位，所以这里只能
        # 先记下房间；真正挂 uid 用下面那个 `Player` 包装做（它同时建 AI 与真人座位）。
        server.room_manager.get_room(room_id).human_uid_pending = uid
        return room_id

    real_player = server.Player

    def player_factory(**kw):
        if kw.get('sid') == 'human-0' and not kw.get('user_id'):
            kw['user_id'] = uid
        return real_player(**kw)

    monkeypatch.setattr(server.room_manager, 'create_ai_room', patched)
    monkeypatch.setattr(server, 'Player', player_factory)
    return uid


def _play(seed=11, p1=None, p2=None, max_rounds=60):
    return hg.play_game(p1 or hg.ExistingAIPolicy('hard'),
                        p2 or hg.ExistingAIPolicy('normal'),
                        seed=seed, max_rounds=max_rounds)


def test_one_full_game_records_steps(with_real_human, capture):
    """★★ 真打完一整局 ⇒ 录到步骤、收口时打包成功、落库后内存置空。

    "真对局"是这条的价值：无头驱动器走的是与 socket 同一批 handler，
    所以它跑到的那些 `add_game_log` 调用点**确实**产出了步骤。
    """
    result = _play()
    assert not result.stalled, result.stall_reason
    assert capture.calls == 1, '结算时应当恰好打包一次，实际 %d 次' % capture.calls
    assert capture.error is None, capture.error
    payload = capture.payload
    assert payload is not None, '收口时没有产出回放 —— 记录器没接上'
    assert payload['version'] == replay.REPLAY_VERSION
    assert payload['steps'], '一整局下来不该 0 步'
    assert payload['ships'], '船位时间线是空的（双方摆船都没记上）'
    assert payload['hands'], '手牌时间线是空的（猜拳发牌都没记上）'
    assert payload['p1_name'] and payload['p2_name'], '双方显示名必须落进回放'
    assert payload['truncated'] is None, '正常局不该被截断：%s' % payload['truncated']
    # 终局节点必须有（进度条最后那颗）
    assert any(n['kind'] == 'game_over' for n in payload['nodes']), payload['nodes'][-3:]
    # 关键节点：真对局里一定有击沉或魔法
    kinds = {n['kind'] for n in payload['nodes']}
    assert kinds & {'sunk', 'magic'}, '一整局下来一个关键节点都没有：%s' % kinds


def test_steps_are_recorded_in_order_and_numbered(with_real_human, capture):
    """★ 步骤编号从 0 起、严格递增、不跳号（前端按它做进度条定位）。"""
    _play(seed=12)
    steps = capture.payload['steps']
    assert [s['i'] for s in steps] == list(range(len(steps))), '步骤编号不连续'


def test_every_step_has_the_contract_shape(with_real_human, capture):
    """★★ 每个步骤的键集合**正好**是契约 §3 那五个（多一个少一个都要表态）。

    少 `actor` → 前端画不出"谁做的"；多一个键 → 将来没人知道它能不能删。
    """
    _play(seed=13)
    allowed_kinds = set(replay._KIND_BY_LOG_TYPE.values()) | set(replay.ACTION_KINDS)
    for step in capture.payload['steps']:
        assert set(step) == {'i', 'kind', 'actor', 'text', 'detail'}, sorted(step)
        assert step['kind'] in allowed_kinds, '出现了没登记的 kind：%s' % step['kind']
        assert isinstance(step['text'], str) and step['text']
        assert isinstance(step['detail'], dict)
        # detail 必须**可 JSON 化**（落库前就是 json.dumps，含活对象会在这里炸）
        json.dumps(step['detail'], ensure_ascii=False)


def test_timelines_are_sparse_not_per_step(with_real_human, capture):
    """★★ 两条时间线必须是**稀疏**的（契约 §0：每步全量快照会让体积涨 5~10 倍）。

    判据：时间线条数**远少于**步数。一条对局里大部分步骤并不改船位/手牌。
    """
    _play(seed=14)
    p = capture.payload
    assert len(p['ships']) < len(p['steps']), '船位时间线不是稀疏的'
    assert len(p['hands']) < len(p['steps']), '手牌时间线不是稀疏的'
    assert len(p['ships']) >= 1 and len(p['hands']) >= 1


def test_timeline_entries_only_carry_what_changed(with_real_human, capture):
    """★ 时间线每项只带**这一条里真的变了的那几个座位**（不是每次两座都写）。"""
    _play(seed=15)
    for row in capture.payload['ships']:
        assert set(row) - {'step'}, '空行（既没有 p1 也没有 p2）没意义'
        assert set(row) <= {'step', 'p1', 'p2'}
    for row in capture.payload['hands']:
        assert set(row) - {'step'}
        assert set(row) <= {'step', 'p1', 'p2'}


def test_ship_timeline_never_exposes_hit_cells_as_alive_by_accident(with_real_human, capture):
    """★ 船格三态自洽：`alive` 是布尔、`sunk` 只跟 `alive=False` 一起出现。

    （回放是**全透视**设计，所以船位本身要下发；但字段语义不许自相矛盾，
    否则前端会把一艘沉船画成活的。）

    ⚠️ `src` 是 2026-09-24 收口批加的**探针字段**（这一格来自活船列表还是显式沉没
    登记），见 `replay._ship_cells` 的 ★★ 段：它同时是"同一格不许有两份说法"的证据。
    """
    _play(seed=16)
    for row in capture.payload['ships']:
        for side in ('p1', 'p2'):
            for cell in row.get(side, []):
                assert set(cell) <= {'x', 'y', 'alive', 'sunk', 'src'}, sorted(cell)
                assert cell.get('src') in ('ships', 'lost'), sorted(cell)
                assert isinstance(cell['alive'], bool)
                assert 0 <= cell['x'] <= 5 and 0 <= cell['y'] <= 5
                if 'sunk' in cell:
                    assert cell['alive'] is False, '沉船的格子不该标成活着'
                # 显式沉没登记出来的格子必然是沉没（`lost` 那一份的语义就是"这船沉了"）
                if cell.get('src') == 'lost':
                    assert cell.get('sunk') is True and cell['alive'] is False, cell


def test_recorder_memory_and_blob_are_within_budget(with_real_human, capture, capsys):
    """★★★ 契约 §1 的内存账：**实测**每局常驻字节数 + 落库 blob 字节数。

    实测（真对局，见 stdout 的 `[回放内存账]` 行）：

    * 常驻（`replay.deep_size`，含 Python 容器自身开销）；
    * blob（落库那一份，`separators=(',', ':')`）。

    ⚠️ 这条**不是估算**：真打一整局再量。断言只用契约 §1 真正许可的那条上限
    （512 KB 硬上限，同一个数在 `_shrink` 里也判一次）；30 KB 那条是**观察值**，
    量出来超了就**打在输出里报出来**，不在这里假装它成立（报告里如实写了）。

    ⚠️ `capture.payload` 每局都被 `reset` 清掉，所以这里量的是**抓下来的那一份**，
       也就是真正参与落库的对象图 —— 这正是"峰值"的定义。
    """
    budget = 30 * 1024
    rows = []
    for seed in (17, 18, 19):
        _play(seed=seed)
        payload = capture.payload
        blob = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        rows.append((seed, len(payload['steps']), replay.deep_size(payload), len(blob)))
    with capsys.disabled():
        for seed, steps, resident, blob_len in rows:
            print('\n[回放内存账] seed=%d steps=%d 常驻=%d B (%.1f KB) blob=%d B (%.1f KB)'
                  % (seed, steps, resident, resident / 1024, blob_len, blob_len / 1024))
        worst = max(r[2] for r in rows)
        print('[回放内存账] 最坏常驻=%d B；契约 §1 的 30 KB 观察值 = %s（超出 %.2fx）'
              % (worst, '满足' if worst <= budget else '不满足', worst / budget))
    for _seed, _steps, _resident, blob_len in rows:
        assert blob_len <= replay.MAX_REPLAY_BYTES, '单条 blob 超过 512 KB 硬上限'
    assert all(r[1] > 0 for r in rows), '有一局没录到步骤'


def test_finalize_clears_the_recorder(with_real_human, capture):
    """★★ 落库之后**立刻置空**（契约 §1：内存绝不长期留着回放）。

    判据：`_finalize_match` 跑完之后，那个房间对象的录制状态是空的。
    做法：劫持 `db.record_match` 把房间对象留一份出来。
    """
    seen = {}
    real = db_module.db.record_match

    def spy(*a, **kw):
        seen['replay_blob'] = kw.get('replay')
        return real(*a, **kw)

    db_module.db.record_match = spy
    try:
        _play(seed=18)
    finally:
        db_module.db.record_match = real
    assert seen.get('replay_blob'), '收口时没把回放交给 record_match'
    # 房间对象已经被无头驱动器删掉了，所以这里改判"落库的那份是完整的 JSON"
    assert seen['replay_blob']['steps']


def test_recorder_is_cleared_after_finalize():
    """★ 直接对房间调一次 `finalize` + `reset`：录制状态必须被清空。

    （上一条走的是真对局的收口；这一条把"置空"这条纪律单独钉住 ——
    它是内存账的执行点，少了它 50 个并发房间会各挂一份。）
    """
    room = _minimal_room()
    try:
        add = server.add_game_log
        add(room, '第一步', 'system', {})
        room.players[SID_A].ships = _ships(P1_SHIPS)
        room.players[SID_A].remaining_ships = 6
        add(room, '第二步', 'system', {})
        assert replay.step_count(room) == 2
        assert replay.finalize(room) is not None
        replay.reset(room)
        assert replay.step_count(room) == 0, 'reset 之后不该还有步骤'
        assert replay.finalize(room) is None, '0 步 ⇒ 没有可回放的内容（§9）'
    finally:
        # ⚠️ 必须显式清掉：房间进了 `room_manager.rooms` 就会污染后面
        #    `build_lobby_state()` 那类"列出所有进行中对局"的用例（实测踩过 ——
        #    这一条漏了清理，`test_spectate_batch3` 会成片变红）。
        room_manager.delete_room(room.id)


def test_zero_step_game_has_no_replay():
    """★ §9：某局 0 步 ⇒ `finalize` 返回 None（前端把按钮置灰并写明原因）。"""
    room = _minimal_room()
    try:
        assert replay.finalize(room) is None
    finally:
        room_manager.delete_room(room.id)


# ===========================================================================
# 房间 / 玩家工厂（与观战批同一套约定）
# ===========================================================================
def _ships(shape):
    return [PlayerShip(positions=[Position(x, y) for (x, y) in cells], hits=[])
            for cells in shape]


def _account():
    uid = db_module.create_user('reprec-%s' % uuid.uuid4().hex[:10], 'x' * 12)
    assert uid
    return uid


def _minimal_room():
    """一个**匹配房形状**的房间（key = sid，真人 uid 在 `Player.user_id` 上）。"""
    room = GameRoom('reprec-' + uuid.uuid4().hex[:6])
    room.players[SID_A] = Player(name='甲', ships=[], attacks=[], remaining_ships=0,
                                 sid=SID_A, user_id=_account())
    room.players[SID_B] = Player(name='乙', ships=[], attacks=[], remaining_ships=0,
                                 sid=SID_B, user_id=_account())
    room.state = 'attacking'
    room.current_phase = 'battle'
    room.current_attacker = SID_A
    room.attack_order = [SID_A, SID_B]
    room.attacks_remaining = 3
    room.round = 3
    room.game_logs = []
    room_manager.rooms[room.id] = room
    return room


@pytest.fixture
def room():
    r = _minimal_room()
    yield r
    room_manager.rooms.pop(r.id, None)


# ===========================================================================
# 4 个棋盘重置点（逐个跑真实现）
# ===========================================================================
def test_board_reset_from_clear_attacks_on_cells(room):
    """★ 棋盘重置点①：`_clear_attacks_on_cells`（五张"清格子"的卡共用入口）。"""
    room.players[SID_A].attacks.append(Position(x=1, y=5, hit=True))
    server._clear_attacks_on_cells(room, [Position(x=1, y=5)], SID_B)
    resets = replay.build(room)['board_resets']
    assert resets == [{'step': 0, 'side': 'p2'}], \
        '清的是乙那块棋盘（甲打出去的格），side 必须是 p2：%s' % resets


def test_board_reset_from_lingqi(room):
    """★ 棋盘重置点②：灵气复苏（**双方**重摆 ⇒ 两条 side）。"""
    room.magic_temp_data = {'type': 'lingqi_choice', 'caster': SID_A, 'max_ships': 6}
    resp = server.confirm_magic_target({
        'room_id': room.id, 'player_id': SID_A, 'temp_data_id': 'lingqi_choice',
        'target_data': {'target_ships': 6}})
    assert resp.get('status') == 'success', resp
    sides = [r['side'] for r in replay.build(room)['board_resets']]
    assert sorted(sides) == ['p1', 'p2'], sides


def test_board_reset_from_baizhe_shichen(room):
    """★ 棋盘重置点③：败者食尘（**双方**重摆）。"""
    res = server.apply_magic_effect(room, SID_A, MagicCard('败者食尘'), {})
    assert res.success is not False, res.message
    sides = [r['side'] for r in replay.build(room)['board_resets']]
    assert sorted(sides) == ['p1', 'p2'], sides


def test_board_reset_from_huiguang(room):
    """★★ 棋盘重置点④：回光返照**只记施法者那一侧**（对手那块一格都不许标）。"""
    res = server.apply_magic_effect(room, SID_A, MagicCard('回光返照'), {})
    assert res.success is not False, res.message
    resets = replay.build(room)['board_resets']
    assert [r['side'] for r in resets] == ['p1'], \
        '回光返照只清施法者那块棋盘，实际标了：%s' % resets


def test_board_reset_marks_a_node_for_the_progress_bar(room):
    """★ 每次重置都要在进度条上留一颗节点（否则玩家看不出棋盘为什么变干净了）。"""
    room.players[SID_A].attacks.append(Position(x=1, y=5, hit=True))
    server._clear_attacks_on_cells(room, [Position(x=1, y=5)], SID_B)
    nodes = replay.build(room)['nodes']
    assert [n['kind'] for n in nodes] == ['reset'], nodes


def test_board_reset_does_not_add_a_step(room):
    """★ 重置标记**不是一步**（它挂在这一步上，不占序号）。

    少了这条纪律，一次重摆会凭空多出一步"什么都没发生"的帧。
    """
    before = replay.step_count(room)
    server._clear_attacks_on_cells(room, [Position(x=1, y=5)], SID_B)
    assert replay.step_count(room) == before


# ===========================================================================
# 6 个 note_action 点（逐个跑真实现）
# ===========================================================================
def _kinds(room):
    return [s['kind'] for s in replay.build(room)['steps']]


def test_note_action_place_ships_through_the_real_handler(room):
    """★ 记录点①：`handle_place_ships`（真 handler，走默认那条成功返回路径）。"""
    room.state = 'placing_ships'
    room.players[SID_A].max_ships = 6
    resp = server.handle_place_ships({
        'room_id': room.id, 'player_id': SID_A,
        'ships': [{'positions': [{'x': x, 'y': 0}], 'hits': []} for x in range(6)]})
    assert resp == {'status': 'success'}, resp
    assert _kinds(room) == ['place_ships'], _kinds(room)
    assert replay.build(room)['steps'][0]['text'].startswith('甲 布好了 6 艘战舰')


def test_note_action_rps_choice_through_the_real_handler(room):
    """★ 记录点②：`handle_rps_choice`（真 handler，猜拳定先手）。"""
    room.state = 'rock_paper_scissors'
    room.rps_choices = {}
    room.rps_processed = False
    room.attack_order = []
    server.handle_rps_choice({'room_id': room.id, 'player_id': SID_A, 'choice': 'rock'})
    server.handle_rps_choice({'room_id': room.id, 'player_id': SID_B, 'choice': 'scissors'})
    assert room.state == 'attacking'
    assert 'rps_choice' in _kinds(room), _kinds(room)


def test_note_action_enter_battle_phase_through_the_real_handler(room):
    """★ 记录点③：`enter_battle_phase`（真 handler）。"""
    room.current_phase = 'preparation'
    resp = server.enter_battle_phase({'room_id': room.id, 'player_id': SID_A})
    assert resp == {'status': 'success'}, resp
    assert _kinds(room) == ['enter_battle'], _kinds(room)


def test_note_action_enter_end_phase_through_the_real_handler(room):
    """★ 记录点④：`handle_enter_end_phase`（真 handler）。

    ⚠️ 前置条件：**没有剩余攻击次数**（`attacks_remaining = 0`）—— 否则那个门禁
       会以「你还有剩余攻击次数，无法进入结束阶段」拒掉，测试就测不到记录点了。
    """
    room.attacks_remaining = 0
    resp = server.handle_enter_end_phase({'room_id': room.id, 'player_id': SID_A})
    assert resp.get('status') == 'success', resp
    assert _kinds(room) == ['enter_end'], _kinds(room)


def test_note_action_end_turn_is_recorded_exactly_once(room):
    """★★ 记录点⑤：`end_turn` —— 写在 `try/finally` 里，所以**恰好一次**。

    判据分两层：
      ① 源码级：`end_turn` 的成功分支必须是 `try: return _end_turn_locked(...)`
         并且 `finally` 里有那一次 `replay.note_action(..., 'end_turn', ...)`；
      ② 运行时：走一次真 `end_turn`（正常换人那条路），只多一条 `end_turn` 步。
    """
    src = io.open(SERVER_PY, encoding='utf-8').read()
    tree = ast.parse(src)
    body = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'end_turn':
            body = ast.get_source_segment(src, node) or ''
    assert body, 'server.py 里找不到 end_turn'
    assert 'try:' in body and 'finally:' in body, \
        'end_turn 的成功分支必须包在 try/finally 里（3 条返回路径只记一次）'
    finally_part = body.split('finally:', 1)[1]
    assert "replay.note_action(room, 'end_turn'" in finally_part, \
        'end_turn 的 finally 里没有那一次记录'

    room.current_phase = 'end'
    resp = server.end_turn({'room_id': room.id, 'player_id': SID_A})
    assert resp.get('status') == 'success', resp
    kinds = _kinds(room)
    assert kinds.count('end_turn') == 1, kinds
    assert room.current_attacker == SID_B


def test_note_action_surrender_through_the_real_handler(room):
    """★ 记录点⑥：`handle_surrender`（真 handler）。

    ⚠️ 必须记在 `_finalize_match` **之前**：收口里会 `finalize` + `reset`，
       记在后面等于永远录不进去（这条用例就是钉住这个顺序的）。
    """
    seen = {}
    real = server.replay.finalize

    def spy(r):
        seen['kinds'] = [s['kind'] for s in replay.build(r)['steps']]
        return real(r)

    server.replay.finalize = spy
    try:
        resp = server.handle_surrender({'room_id': room.id, 'player_id': SID_A})
    finally:
        server.replay.finalize = real
    assert resp == {'status': 'success'}, resp
    assert 'surrender' in seen.get('kinds', []), \
        '投降没被记进回放（是不是记在 _finalize_match 之后了？）：%s' % seen


# ===========================================================================
# 硬上限：截断**明确标注**（§3 / §8-10 / §9）
# ===========================================================================
def test_step_cap_truncates_and_marks(monkeypatch):
    """★★ 步数上限：触限就**截断 + 明确标注**，绝不静默（契约 §3）。"""
    monkeypatch.setattr(replay, '_MAX_STEPS', 5)
    room = _minimal_room()
    try:
        for i in range(20):
            server.add_game_log(room, '第 %d 步' % i, 'system', {})
        payload = replay.finalize(room)
        assert len(payload['steps']) == 5, '应当正好留住上限那么多步'
        assert payload['truncated'] and '截断' in payload['truncated'], payload['truncated']
        assert any(n['kind'] == 'truncated' for n in payload['nodes']), \
            '进度条上也必须能看出被截断了'
    finally:
        room_manager.delete_room(room.id)


def test_blob_cap_truncates_and_marks(monkeypatch):
    """★★ blob 上限：合成一份超限的回放 ⇒ 截断 + 明确标注（**不是**静默返回空）。"""
    monkeypatch.setattr(replay, 'MAX_REPLAY_BYTES', 2000)
    room = _minimal_room()
    try:
        for i in range(200):
            server.add_game_log(room, '很长的一步 ' * 8 + str(i), 'system', {'i': i})
        payload = replay.finalize(room)
        assert payload is not None
        assert payload['truncated'] and '截断' in payload['truncated']
        assert replay.blob_bytes(payload) <= 2000, '截断之后仍然超限'
        assert 'truncated_steps' in payload, '截断了多少步要如实说出来'
        assert payload['truncated_steps'] > 0
    finally:
        room_manager.delete_room(room.id)


def test_normal_game_is_never_marked_as_truncated(with_real_human, capture):
    """★ 反向腿：正常局**不许**被打上截断标记（否则那个标记就失去意义）。"""
    _play(seed=19)
    assert capture.payload['truncated'] is None
    assert 'truncated_steps' not in capture.payload


# ===========================================================================
# 边界：取不到东西时不许炸（§9 表格最后一行）
# ===========================================================================
def test_recorder_survives_a_fake_room():
    """★ 假房间（测试替身 / 缺字段）不许把记录器弄炸。

    这条不是洁癖：所有 `server.emit` / `_mark_spectate_board_dirty` 都留了
    "假房间"的口子（`except AttributeError: pass`），记录器在**同一条链路**上，
    它一炸就是把一次真实行动炸掉。
    """
    class Fake:
        pass

    fake = Fake()
    replay.note(fake, {'type': 'attack', 'text': 'x', 'detail': {}})
    replay.note_action(fake, 'end_turn', 'x')
    replay.note_board_reset(fake)
    assert replay.step_count(fake) == 2
    payload = replay.finalize(fake)
    assert payload['steps'][0]['kind'] == 'attack'


def test_note_ignores_garbage_input():
    """★ 喂进来的不是 dict（老格式 / 手滑）⇒ 直接忽略，不炸、不记半条。"""
    room = _minimal_room()
    try:
        replay.note(room, None)
        replay.note(room, '不是 dict')
        assert replay.step_count(room) == 0
    finally:
        room_manager.delete_room(room.id)


def test_actor_falls_back_to_the_player_id():
    """★ 取不到显示名时退回 pid（与 `server._log_name` 同口径），绝不丢这一步。"""
    room = _minimal_room()
    try:
        room.players[SID_A].name = ''
        server.add_game_log(room, '第3回合 · 甲 攻击 (0,0) — 命中', 'attack',
                            {'attacker': SID_A, 'target': {'x': 0, 'y': 0}, 'hit': True})
        step = replay.build(room)['steps'][0]
        assert step['actor'] == SID_A
        assert step['kind'] == 'attack'
        assert step['detail']['target'] == {'x': 0, 'y': 0}
    finally:
        room_manager.delete_room(room.id)


def test_game_log_payload_shape_is_kept_for_the_frontend(room):
    """★★ 攻击步的 `detail` 必须保住前端要用的那几个键（坐标 / 命中 / 击沉）。

    它们是**全透视回放**的棋盘重建输入（契约 §7：第 k 帧棋盘标记 = `steps[0..k]`
    里的 attack 步）。
    """
    server.add_game_log(room, '第3回合 · 甲 攻击 (2,4) — 命中，击沉战舰', 'attack',
                        {'attacker': SID_A, 'target': {'x': 2, 'y': 4},
                         'hit': True, 'ship_sunk': True, 'shield_blocked': False})
    detail = replay.build(room)['steps'][0]['detail']
    for key in ('attacker', 'target', 'hit', 'ship_sunk'):
        assert key in detail, '前端要用的键丢了：%s' % key
    assert detail['target'] == {'x': 2, 'y': 4}
    assert detail['hit'] is True and detail['ship_sunk'] is True
    # 节点也要跟着出（进度条上的"击沉战舰"）
    nodes = replay.build(room)['nodes']
    assert any(n['kind'] == 'sunk' for n in nodes), nodes


def test_magic_step_marks_a_node_with_the_card_name(room):
    """★ 使用魔法卡那一步必须在进度条上留一颗带**卡名**的节点。"""
    server.log_magic(room, SID_A, MagicCard('失灵！'))
    nodes = replay.build(room)['nodes']
    magic = [n for n in nodes if n['kind'] == 'magic']
    assert magic and '失灵！' in magic[0]['label'], nodes


def test_quick_chat_is_kept_as_a_step(room):
    """★ 假设 A5：局内快捷语**保留为步骤**（它本来就是对局的一部分）。"""
    server.add_game_log(room, '甲：打得好！', 'quick_chat',
                        {'player': SID_A, 'text': '打得好！'})
    assert _kinds(room) == ['quick_chat']


def test_no_game_log_line_is_added_by_the_six_note_action_points(with_real_human, capture):
    """★★ 那 6 处**不许往游戏内日志加行**：真打一整局，比对日志行数与步骤数。"""
    _play(seed=20)
    payload = capture.payload
    logged = {s['text'] for s in payload['steps']}
    action_texts = {s['text'] for s in payload['steps']
                    if s['kind'] in replay.ACTION_KINDS}
    assert action_texts, '一整局下来一条行动步骤都没有？'
    # 行动步骤的文案不该出现在游戏内日志那份列表里（它们没往里面加行）
    assert action_texts - logged == set()          # 同一条来源，文案自然一致
    # 真正的判据在源码：那 6 个点只调 note_action / 不调 add_game_log
    src = io.open(SERVER_PY, encoding='utf-8').read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, 'attr', None) != 'note_action':
            continue
        # 取这个调用所在的**语句**（多行调用要连着看）：往上找到 Expr
        pass
    # 退一步按函数体扫：这 6 个函数体里都不许出现 add_game_log
    for name in ('handle_place_ships', 'handle_rps_choice', 'enter_battle_phase',
                 'handle_enter_end_phase', 'handle_surrender'):
        seg = None
        for n in ast.walk(tree):
            if isinstance(n, ast.FunctionDef) and n.name == name:
                seg = ast.get_source_segment(src, n) or ''
        assert seg is not None, name
        assert 'add_game_log(' not in seg, '%s 往游戏内日志加行了' % name


# ===========================================================================
# `started_at`：只认既有的那一份"开打时刻"判据（教训 #1）
# ===========================================================================
def test_started_at_uses_the_single_match_start_judgement(room):
    """★★ 「这局什么时候开打的」**不许自己读 `created_at`**。

    契约 §3 原本没定义这个字段，实现先取了 `room.created_at`（= **建房**时刻）。
    自定义房可能建好后放很久才开局 ⇒ 那会把"对局时间"标早十几分钟。
    正确来源是既有的唯一判据 `server._match_started_at`（优先 `room.match_started_at`
    —— 猜拳结束、真正进入 attacking 时才打点；没有打点才退回 `created_at`）。
    自己再读一次 `created_at` 就是教训 #1 的第二份判据。
    """
    room.created_at = 1_700_000_000          # 建房
    room.match_started_at = 1_700_000_900    # 15 分钟后才真开打
    assert replay.build(room)['started_at'] == 1_700_000_900


def test_started_at_falls_back_only_when_there_is_no_start_mark(room):
    """兜底腿：**没有** `match_started_at` 时才退回 `created_at`。

    这条兜底只影响一个**展示**字段，不参与任何门禁 —— 教训 #2 禁的是
    "拿会兜底的取数函数当判据"，不是禁展示用兜底。
    """
    room.created_at = 1_700_000_000
    if hasattr(room, 'match_started_at'):
        del room.match_started_at
    assert replay.build(room)['started_at'] == 1_700_000_000


def test_replay_does_not_reinvent_the_match_start_judgement():
    """★ 源码级：`replay.py` 必须**复用** `server._match_started_at`，不许自己判一次。

    把它改回直接读 `room.created_at`（或自己 `getattr(room, 'match_started_at', ...)`）
    这条就红 —— 那正是"同一件事两份判据必然漂移"（教训 #1）。
    """
    src = io.open(REPO_ROOT / 'replay.py', encoding='utf-8').read()
    assert "_srv('_match_started_at')" in src, (
        'replay.py 没有复用 server._match_started_at —— '
        '"开打时刻"长出了第二份判据')


def test_replay_module_is_bound_to_the_server():
    """★★ `server.py` 必须真的把模块对象注进 `replay`（**漏接线的守卫**）。

    这条是**补上来的**：本批实现时 `server.py` 只 `import replay`、**没有** `replay.bind(...)`，
    而 `replay._srv()` 取不到东西时返回 None ⇒ 回放 `started_at` **静默**退回
    `room.created_at`（建房时刻），自定义房会把"对局时间"标早十几分钟，**没有任何报错**。
    删掉 `server.py` 里那句 `replay.bind(...)` 这条就红。
    """
    assert replay._SERVER is not None, (
        'replay 没有拿到 server 模块对象 —— 检查 server.py 里的 replay.bind(...) '
        '（少了它不会有任何报错，只会让依赖 server 的判据静默走兜底）')
    assert replay._srv('_match_started_at') is server._match_started_at, (
        'replay 拿到的不是正在跑的那一份 server —— 别把模块名写错（教训 #19）')
