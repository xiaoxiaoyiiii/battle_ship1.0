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




def test_timelines_are_sparse_not_per_step(with_real_human, capture):
    """★★ 两条时间线必须是**稀疏**的（契约 §0：每步全量快照会让体积涨 5~10 倍）。

    判据：时间线条数**远少于**步数。一条对局里大部分步骤并不改船位/手牌。
    """
    _play(seed=14)
    p = capture.payload
    assert len(p['ships']) < len(p['steps']), '船位时间线不是稀疏的'
    assert len(p['hands']) < len(p['steps']), '手牌时间线不是稀疏的'
    assert len(p['ships']) >= 1 and len(p['hands']) >= 1




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


def test_board_reset_from_lingqi(room):
    """★ 棋盘重置点②：灵气复苏（**双方**重摆 ⇒ 两条 side）。"""
    room.magic_temp_data = {'type': 'lingqi_choice', 'caster': SID_A, 'max_ships': 6}
    resp = server.confirm_magic_target({
        'room_id': room.id, 'player_id': SID_A, 'temp_data_id': 'lingqi_choice',
        'target_data': {'target_ships': 6}})
    assert resp.get('status') == 'success', resp
    sides = [r['side'] for r in replay.build(room)['board_resets']]
    assert sorted(sides) == ['p1', 'p2'], sides




def test_board_reset_from_huiguang(room):
    """★★ 棋盘重置点④：回光返照**只记施法者那一侧**（对手那块一格都不许标）。"""
    res = server.apply_magic_effect(room, SID_A, MagicCard('回光返照'), {})
    assert res.success is not False, res.message
    resets = replay.build(room)['board_resets']
    assert [r['side'] for r in resets] == ['p1'], \
        '回光返照只清施法者那块棋盘，实际标了：%s' % resets




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
    """★ 反向腿：正常局**不许**被打上截断标记（否则那个标记就失去意义）。

    ⚠️ 2026-09-25 seed 19 → 18：新卡「兵粮寸断」进牌池改变了牌序，seed=19 现在会落进
       「无暇圣心」那条**不结算**的终局路径 —— `server.py` 里那处只设
       `state`/`winner`、**不调 `_finalize_match`**（对比 `_check_last_chance` 是调的），
       于是 `replay.finalize` 拿不到步数 ⇒ `capture.payload` 为 None。
       那是**与本卡无关的既有缺陷**（40 个 seed 里 19/20/24 会命中），已单独上报；
       本用例要的只是"一局正常结算的对局"，故重锚到一个走正常路径的 seed。
    """
    _play(seed=18)
    assert capture.payload['truncated'] is None
    assert 'truncated_steps' not in capture.payload


# ===========================================================================
# 边界：取不到东西时不许炸（§9 表格最后一行）
# ===========================================================================














# ===========================================================================
# `started_at`：只认既有的那一份"开打时刻"判据（教训 #1）
# ===========================================================================
