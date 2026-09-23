# -*- coding: utf-8 -*-
"""对局回放的**纯模块**：记录器 + 终局打包（契约见 `docs/REPLAY_2026_09_23.md` §2~§6）。

与 `ranks.py` / `spectate.py` / `quick_chat.py` 同路数：**纯函数、无 I/O、无 socket、
运行期绝不 `import server`**（CLAUDE.md 教训 #19：`python server.py` 时本模块名是
`__main__`，`import server` 会把整个 server.py 再执行一遍成**另一个模块对象** ——
那份 `socketio` 发不出事件、那份 `room_manager` 建的房在真进程里不存在，
而 pytest 里 server 就叫 `server`，**这类 bug pytest 永远测不到**，
守卫只能是源码级断言，见 `tests/test_replay_guards.py::test_replay_never_imports_server`）。

需要 server 的能力时，由 server.py 在 **import 期注入模块对象**（`bind()`），
本模块**按名字现取**（`_srv('...')`）—— 注入**函数对象**会把测试里的 monkeypatch
静默架空（教训 #19 后半句），所以注入的只有模块对象自己。

## 铁律：记录器**绝不 emit 任何东西**

回放数据里有**双方船位**。一旦这条数据进了对局房间（`emit(...)` / `socketio.emit`），
就是对局双方与观众当场拿到全透视 —— 灾难级泄露，而且**零报错**。
所以本模块连 `emit` / `socketio` 这两个词都不许出现（源码级守卫同上文件）。

## 数据形状（前端的唯一契约）

一条回放 = **现有 `game_logs` 的步骤序列 + 两条稀疏时间线（船位 / 手牌）+ 棋盘重置标记**。
不存每步全量快照（那会让体积涨 5~10 倍）。

* `steps[i] = {i, kind, actor, text, detail}` —— 按行动顺序；
* `ships[i] = {step, p1: [{x, y, alive, sunk}], p2: [...]}` —— **只在船位真变时**记一条；
* `hands[i] = {step, p1: ['卡名', ...], p2: [...]}`      —— **只在手牌真变时**记一条；
* `board_resets[i] = {step, side}`                        —— `side` 是 `'p1'` / `'p2'`；
* `nodes[i] = {step, kind, label}`                        —— 进度条关键节点，**服务端算一次**。

⚠️ 玩家代号（`p1` / `p2`）**只在 `finalize()` 里按 `room.players` 的插入顺序算一次**
（与 `spectate.seat_order` 同一口径：插入顺序 = 入座顺序）。录制期间一律用**原始 pid**
当键，避免录制与打包两处各算一次而漂移（教训 #1）。
"""
from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# 版本与硬上限（契约 §3，数字只有这一份）
# ---------------------------------------------------------------------------
#: 回放 JSON 的格式版本。**它同时是"读接口要不要拒收"的判据**（契约 §6）：
#: 版本对不上 ⇒ 明确报错，绝不静默返回半份数据。
REPLAY_VERSION = 1

#: 步数上限（契约 §3）。触限 ⇒ **截断 + 明确标注**，绝不静默。
MAX_STEPS = 2000

#: 落库 blob 的硬上限（512 KB）。**读的时候也按它拒收**（契约 §1、§6）：
#: 坏 blob 不许打爆 1.8 GB 的机器（线上实测：可用 777 MB + 已在 swap）。
MAX_REPLAY_BYTES = 512 * 1024

#: 记录器在**一局之内**允许占用的最大步数 —— 与 `MAX_STEPS` 同一个数，
#: 但它管的是"内存里不许无界增长"（超了就丢弃后续步并打标记）。
_MAX_STEPS = MAX_STEPS

#: 截断时给玩家/前端看的说明（**绝不静默**：契约 §3）。
TRUNCATED_TEXT = '此回放被截断'

#: 回放数据挂在房间上的属性名。放房间级字段而不是 `magic_temp_data`
#: （教训 #30：`magic_temp_data` 有 8 处被整体覆写 `= {}`）。
_ROOM_ATTR = 'replay'

# game_log 的 `type` → 回放步骤的 `kind`。**只做一次映射**，前端按 `kind` 分支。
_KIND_BY_LOG_TYPE = {
    'attack': 'attack',
    'magic': 'magic',
    'quick_chat': 'quick_chat',
    'result': 'game_over',
    'system': 'system',
    'info': 'system',
    'achievements': 'system',
    'xp': 'system',
    'rank': 'system',
}

#: 进度条节点只认这几种（前端按 `kind` 画不同颜色）。
NODE_KINDS = ('magic', 'sunk', 'reset', 'phase', 'game_over', 'truncated')

#: 攻击步里**可以剥掉**的派生字段（只有"客户端能自己算出来"的才配进这张表）。
#:
#: * `shield_blocked` —— 前端重建棋盘只用 `hit` / `ship_sunk` / `target`（契约 §7），
#:   而"被护盾挡下"这件事文案里已经写了；实测每局省 6~7 KB（**信息一点没少**）。
#:   `hit` / `ship_sunk` **不许**剥：它们是"这一格画 ✕ 还是 ○ / 要不要加「沉」"的
#:   直接输入，剥了就得让前端去解析文案（那就长出第二份规则了 —— 教训 #1）。
#: 判据：`'target' in payload`（只有攻击步有 `target`，不会误伤别的 detail）。
_DETAIL_DERIVED_KEYS = ('shield_blocked',)

#: 六个"没有游戏内日志的行动"的 kind（契约 §3 第 2 条）。
ACTION_KINDS = ('place_ships', 'rps_choice', 'enter_battle', 'enter_end',
                'end_turn', 'surrender')

# ---------------------------------------------------------------------------
# 反向注入：server.py 在 import 期把**模块对象自己**交进来（不是一个函数）
# ---------------------------------------------------------------------------
_SERVER = None


def bind(server_module) -> None:
    """由 `server.py` 在 import 期调用：把 server 模块对象交给本模块。

    ⚠️ 注入的是**模块对象**，调用点一律 `getattr(_SERVER, 名字)` 现取
       （`_srv()`）—— 注入函数对象会把测试里的 monkeypatch **静默架空**
       （教训 #19）。没有 server（纯单测）时 `_srv()` 返回 None，
       记录器**照常工作**（它只需要 room 对象，不需要 server 的任何能力）。
    """
    global _SERVER
    _SERVER = server_module


def _srv(name):
    """按名字从注入的 server 模块取属性（取不到返回 None，绝不抛）。"""
    if _SERVER is None:
        return None
    return getattr(_SERVER, name, None)


# ---------------------------------------------------------------------------
# 房间上的状态（三件齐：这里初始化 + 明确消费点 + 回归用例）
# ---------------------------------------------------------------------------
def _state(room):
    """取房间的回放状态；没有就**惰性建**（`GameRoom.__init__` 也建了一份）。"""
    st = getattr(room, _ROOM_ATTR, None)
    if isinstance(st, dict):
        return st
    st = {
        'steps': [],
        'ships': [],        # 船位时间线（稀疏）
        'hands': [],        # 手牌时间线（稀疏）
        'board_resets': [],  # [{step, side}]
        'nodes': [],        # [{step, kind, label}]
        'last': None,       # 上一次快照（用来判"真的变了吗"）
        'truncated': None,  # None = 没截断；否则是原因字符串
    }
    try:
        setattr(room, _ROOM_ATTR, st)
    except Exception:       # noqa: BLE001 —— 假房间（测试替身）不挂属性也不许抛
        pass
    return st


def reset(room) -> None:
    """清空这一局的录制状态（重开一局 / 终局落库之后）。**唯一实现**。"""
    if room is None:
        return
    try:
        setattr(room, _ROOM_ATTR, None)
    except Exception:       # noqa: BLE001
        pass


def step_count(room) -> int:
    """已经录了多少步（0 = 这局什么行动都没有）。"""
    st = getattr(room, _ROOM_ATTR, None)
    if not isinstance(st, dict):
        return 0
    return len(st.get('steps') or [])


def is_truncated(room):
    """`None` = 没截断；否则返回**原因字符串**（绝不静默，契约 §3）。"""
    st = getattr(room, _ROOM_ATTR, None)
    if not isinstance(st, dict):
        return None
    return st.get('truncated')


# ---------------------------------------------------------------------------
# 稀疏快照
# ---------------------------------------------------------------------------
def _pids(room):
    """座位顺序的原始 pid 列表（与 `spectate.seat_order` 同一口径）。"""
    players = getattr(room, 'players', None)
    if isinstance(players, dict):
        return list(players.keys())
    return []


def _side_label(room, pid):
    """pid → `'p1'` / `'p2'`（认不出来返回 None，绝不回显原始 pid）。"""
    order = _pids(room)
    try:
        idx = order.index(pid)
    except ValueError:
        return None
    return 'p%d' % (idx + 1) if idx < 2 else None


def _is_alive(ship) -> bool:
    """存活判据与全局同一份：`len(hits) < len(positions)`。"""
    try:
        return len(ship.hits) < len(ship.positions)
    except Exception:       # noqa: BLE001 —— 假船对象：按"活着"处理，不炸
        return True


def _ship_cells(player):
    """该座位**摆放中/已摆放**的全部船格：`[{'x','y','alive','sunk'}]`。

    * `alive` = 这一格所属的船**还没沉**（`len(hits) < len(positions)`）；
    * `sunk`  = 船已沉（前端画「沉」，与实战棋盘同口径）。

    ⚠️ 这份数据**只对回放看客**存在（自己/别人战绩里点开的那一屏）。
       它**绝不**经过 `emit()` —— 见模块开头那条铁律。
    """
    out = []
    for ship in (getattr(player, 'ships', None) or []):
        try:
            alive = _is_alive(ship)
            for pos in (getattr(ship, 'positions', None) or []):
                cell = {'x': int(pos.x), 'y': int(pos.y), 'alive': alive}
                if not alive:
                    cell['sunk'] = True
                out.append(cell)
        except Exception:   # noqa: BLE001 —— 假的船对象：跳过这一艘，不炸
            continue
    return out


def _hand_names(player):
    """该座位当前手牌的**卡名**列表（顺序即手牌顺序）。"""
    names = []
    for card in (getattr(player, 'magic_hand', None) or []):
        name = getattr(card, 'name', None)
        names.append(str(name) if name is not None else str(card))
    return names


def _snapshot(room):
    """当前局面的一份稀疏快照 `{pid: {'ships': [...], 'hand': [...]}}`。"""
    snap = {}
    for pid in _pids(room):
        player = room.players.get(pid)
        if player is None:
            continue
        snap[pid] = {'ships': _ship_cells(player), 'hand': _hand_names(player)}
    return snap


def _record_snapshot(room, st, step):
    """快照与上一次**逐字段比对**，真变了才各追加一条时间线（稀疏 + **增量**）。

    ⚠️ 判据必须是"**真的变了吗**"而不是"有没有调用"：`add_game_log` 在 37 个点被调，
    绝大多数调用并不改船位/手牌 —— 每次都记一条会让体积涨 5~10 倍（契约 §0）。

    ★ 每条只写**这一条里真的变了的座位**（另一侧不出现）：前端把它当成**增量**、
    按 `step` 升序合并（契约 §7 的"船位 = 时间线里最后一个 `step ≤ k` 的条目"
    按此实现）。实测（seed=17、5 回合、82 步的真对局）两条时间线合计常驻 19 KB，
    其中只有开局那条同时带 p1/p2，其余每条只带一侧。
    """
    snap = _snapshot(room)
    last = st.get('last')

    def _row(kind_key):
        return {'step': step,
                **{side: snap[pid][kind_key]
                   for pid in snap
                   for side in [_side_label(room, pid)]
                   if side and _changed(pid, kind_key)}}

    def _changed(pid, kind_key):
        if last is None:
            return True
        return (last.get(pid) or {}).get(kind_key) != snap[pid][kind_key]

    ships_row = _row('ships')
    hands_row = _row('hand')
    # `step` 之外一个座位都没有 = 什么都没变（理论上不会走到：调用方先比过）
    if len(ships_row) > 1:
        st['ships'].append(ships_row)
    if len(hands_row) > 1:
        st['hands'].append(hands_row)
    st['last'] = snap


# ---------------------------------------------------------------------------
# 步骤
# ---------------------------------------------------------------------------
def _actor_name(room, pid):
    """pid → 显示名（取不到退回 pid 本身，与 `server._log_name` 同口径）。"""
    player = (getattr(room, 'players', None) or {}).get(pid)
    name = getattr(player, 'name', None) if player is not None else None
    return str(name or pid) if (name or pid) else None


def _step_detail(payload):
    """只留可以 JSON 化的标量/小结构（不复制活对象，教训：别序列化活数据）。

    ⚠️ **攻击步要剥掉两个派生字段**（`hit` / `ship_sunk` 保留，`shield_blocked` 不留）：
       它们是**同一件事的第二次表达** —— 前端的棋盘重建只读 `hit` / `ship_sunk` /
       `target`（契约 §7），文案里也已经写了"被护盾挡下"。实测每局能省下 6~7 KB
       （82 步的局里这一步占 19.5 KB → 12.5 KB），而**一个字节的信息都没少**。
    """
    if not isinstance(payload, dict):
        return {}
    drop = _DETAIL_DERIVED_KEYS if 'target' in payload else ()
    out = {}
    for k, v in payload.items():
        if k in drop:
            continue
        if v is None or isinstance(v, (str, int, float, bool)):
            out[str(k)] = v
        elif isinstance(v, (list, tuple)) and all(
                isinstance(x, (str, int, float, bool)) for x in v):
            out[str(k)] = list(v)
        elif isinstance(v, dict):
            inner = {str(k2): v2 for k2, v2 in v.items()
                     if isinstance(v2, (str, int, float, bool))}
            if inner:
                out[str(k)] = inner
    return out


def _mark_node(st, step, kind, label):
    """记一个进度条关键节点（`kind` 必须在 `NODE_KINDS` 里）。"""
    if kind not in NODE_KINDS:
        return
    st['nodes'].append({'step': step, 'kind': kind, 'label': str(label)})


def _append(room, kind, text, detail=None, actor=None):
    """所有步骤的**唯一追加点**：封顶 + 快照 + 关键节点。"""
    st = _state(room)
    step = len(st['steps'])
    if step >= _MAX_STEPS:
        # 内存里不许无界增长。触限**明确标注**（绝不静默，契约 §3）。
        if not st['truncated']:
            st['truncated'] = '%s（超过 %d 步）' % (TRUNCATED_TEXT, _MAX_STEPS)
            _mark_node(st, step, 'truncated', TRUNCATED_TEXT)
        return None
    entry = {
        'i': step,
        'kind': str(kind),
        'actor': actor,
        'text': str(text),
        'detail': _step_detail(detail),
    }
    st['steps'].append(entry)
    _record_snapshot(room, st, step)
    _node_from_step(st, step, entry)
    return entry


def _node_from_step(st, step, entry):
    """服务端**算一次**关键节点（前端不重新推导，契约 §3）。"""
    kind = entry.get('kind')
    detail = entry.get('detail') or {}
    if kind == 'magic':
        _mark_node(st, step, 'magic', '使用【%s】' % detail.get('card', '魔法卡'))
    elif kind == 'attack':
        if detail.get('ship_sunk'):
            target = detail.get('target') or {}
            _mark_node(st, step, 'sunk',
                       '击沉战舰 (%s,%s)' % (target.get('x'), target.get('y')))
        elif detail.get('hit'):
            target = detail.get('target') or {}
            _mark_node(st, step, 'hit', '命中 (%s,%s)' % (target.get('x'), target.get('y')))
    elif kind == 'game_over':
        _mark_node(st, step, 'game_over', entry.get('text') or '对局结束')


def note(room, entry) -> None:
    """喂一口**游戏内日志**（`add_game_log` 末尾调，一处覆盖 38 个记录点）。

    `entry` 是 `server.GameLog.to_dict()` 的形状：`{ts, type, text, detail}`。
    本函数**不改 entry、不 emit、不写 game_logs** —— 只往房间的回放状态里追加一步。
    """
    if room is None or not isinstance(entry, dict):
        return
    log_type = entry.get('type') or 'info'
    detail = entry.get('detail') if isinstance(entry.get('detail'), dict) else {}
    actor_pid = detail.get('attacker') or detail.get('caster') or detail.get('winner')
    _append(room,
            _KIND_BY_LOG_TYPE.get(log_type, 'system'),
            entry.get('text') or '',
            detail,
            _actor_name(room, actor_pid) if actor_pid else None)


def note_action(room, kind, label, detail=None, actor=None) -> None:
    """喂一口**没有游戏内日志的行动**（契约 §3 第 2 条的 6 个单一实现点）。

    ⚠️ **绝不往 `room.game_logs` 加行**：游戏内日志是既有玩家可见功能，
       本批不改它的显示（加行会让玩家那边凭空多出几条他们没见过的日志）。

    * `kind`   —— 步骤种类（六个之一，见 `ACTION_KINDS`），前端按它画节点；
    * `label`  —— 给玩家看的这一步在做什么（进 `text`，同时做进度条节点文案）；
    * `detail` —— 可选的小 dict（只留标量）；
    * `actor`  —— 可选：行动者的显示名。
    """
    if room is None:
        return
    entry = _append(room, kind, label, detail, actor)
    if entry is not None and kind in ACTION_KINDS:
        _mark_node(_state(room), entry['i'], 'phase', str(label))


def note_board_reset(room, board_owner_id=None) -> None:
    """喂一口**棋盘重置**（复用第 5 批为观战加的 4 个失效点，一处地方两个消费方）。

    * `board_owner_id` = 哪一位的棋盘被换掉了（`回光返照` 只清施法者那一块）；
      传 None 表示双方都换（`灵气复苏` / `败者食尘`）。

    ⚠️ **不能只靠 attack 步反推**：重摆之后棋盘"变干净了"，攻击历史里没有这件事
       （第 5 批那个 bug 的回放版，见契约 §9 表格）。
    """
    if room is None:
        return
    st = _state(room)
    step = len(st['steps'])
    targets = [board_owner_id] if board_owner_id else _pids(room)
    for pid in targets:
        side = _side_label(room, pid)
        if side:
            st['board_resets'].append({'step': step, 'side': side})
    label = '棋盘重置（%s）' % (_actor_name(room, board_owner_id) if board_owner_id
                                else '双方')
    _mark_node(st, step, 'reset', label)


# ---------------------------------------------------------------------------
# 终局打包
# ---------------------------------------------------------------------------
def _blob_bytes(payload) -> int:
    """这一份 payload 落库会占多少字节（`ensure_ascii=False`，与 db 侧一致）。"""
    return len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def _trim_timeline(rows, max_step):
    """把时间线砍到 `step <= max_step`（**保留 step == max_step 的最后一条**）。

    ⚠️ 时间线是**增量**（每条只带变了的座位），所以合并时必须把 `step <= max_step`
       的条目**全部按序叠上去**，不能只取最后一条。
    ⚠️ 也不能简单 `row['step'] <= max_step` 就完：截断点那一帧可能是
       `step == 保留步数`（终局快照）—— 那一帧正是"打完之后"的最终局面，
       砍掉它前端就永远画不出终局棋盘。
    """
    return [row for row in rows if int(row.get('step', -1)) <= max_step]


def build(room):
    """把房间里的录制内容打包成**回放 JSON**（`dict`，可 `json.dumps`）。

    单独拆出来是为了给守卫用例直接断言"打包出来的形状"，不必走落库。
    """
    st = getattr(room, _ROOM_ATTR, None)
    st = st if isinstance(st, dict) else {}
    order = _pids(room)
    names = {}
    for idx, pid in enumerate(order[:2]):
        player = room.players.get(pid)
        names['p%d' % (idx + 1)] = str(getattr(player, 'name', '') or '')

    # 步骤里的 `_side`（录制期用原始 pid 当键）换成 `p1`/`p2`。
    steps = []
    for entry in list(st.get('steps') or []):
        row = dict(entry)
        sides = row.pop('_side', None)
        if sides:
            row['sides'] = sides
        steps.append(row)

    # 「这局什么时候开打的」**只有一个判据**：`server._match_started_at(room)`
    # —— 优先 `room.match_started_at`（猜拳结束、真正进入 attacking 时打点），
    # 没有打点才退回 `room.created_at`。**这里不许自己读 `created_at`**：那会让同一个概念
    # 长出第二份判据（教训 #1），而且自定义房可能建好后放很久才开局，
    # 直接读 `created_at` 会把"对局时间"标早十几分钟。
    # 纯单测没注入 server 时（`_srv()` 返回 None）退回 `created_at`：只影响这一个**展示**字段，
    # 它不参与任何门禁 —— 教训 #2 禁的是"拿会兜底的取数函数当判据"，不是禁展示用兜底。
    started_at = 0
    _started_fn = _srv('_match_started_at')
    if _started_fn is not None:
        started_at = int(_started_fn(room) or 0)
    if not started_at:
        started_at = int(getattr(room, 'created_at', 0) or 0)

    payload = {
        'version': REPLAY_VERSION,
        'p1_name': names.get('p1', ''),
        'p2_name': names.get('p2', ''),
        'started_at': started_at,
        'steps': steps,
        'ships': list(st.get('ships') or []),
        'hands': list(st.get('hands') or []),
        'board_resets': list(st.get('board_resets') or []),
        'nodes': list(st.get('nodes') or []),
        'truncated': st.get('truncated'),
    }
    return payload


def _shrink(payload):
    """blob 超过 `MAX_REPLAY_BYTES` 时**截断并明确标注**（绝不静默，契约 §3）。

    截断顺序（先砍最不重要的）：
      ① 步数折半（同时把时间线砍到同一位置）；
      ② 时间线砍到只剩最后一条；
      ③ 关键节点只留前 200 个。

    仍然超限（理论上不可能：2000 步 × 几百字节 ≈ 几百 KB 以内）时，
    只留最小的合法骨架 + 明确标注 —— **绝不返回半份能骗过前端的 JSON**。
    """
    payload = dict(payload)
    payload['truncated'] = '%s（超过 %d KB）' % (TRUNCATED_TEXT, MAX_REPLAY_BYTES // 1024)
    original_steps = len(payload.get('steps') or [])

    def _too_big(p):
        return _blob_bytes(p) > MAX_REPLAY_BYTES

    # ① 步数折半（直到装得下或只剩 1 步）
    while _too_big(payload) and len(payload.get('steps') or []) > 1:
        keep = max(1, len(payload['steps']) // 2)
        payload['steps'] = payload['steps'][:keep]
        payload['ships'] = _trim_timeline(payload.get('ships') or [], keep)
        payload['hands'] = _trim_timeline(payload.get('hands') or [], keep)
        payload['board_resets'] = [r for r in (payload.get('board_resets') or [])
                                   if int(r.get('step', 0)) <= keep]
        payload['nodes'] = [n for n in (payload.get('nodes') or [])
                            if int(n.get('step', 0)) <= keep]

    # ② 时间线只留最后一条（前端仍能画出终局那一帧）
    if _too_big(payload):
        for key in ('ships', 'hands'):
            rows = payload.get(key) or []
            payload[key] = rows[-1:] if rows else []

    # ③ 节点只留前 200 个
    if _too_big(payload):
        payload['nodes'] = (payload.get('nodes') or [])[:200]

    # ④ 兜底：只留最小骨架（步骤全砍）。**仍然带明确标注**。
    if _too_big(payload):
        payload['steps'] = []
        payload['ships'] = []
        payload['hands'] = []
        payload['board_resets'] = []
        payload['nodes'] = []

    payload['truncated_steps'] = original_steps - len(payload['steps'])
    return payload


def finalize(room):
    """产出最终 JSON 的**唯一入口**：打包 → 上限校验 → 返回 `dict`（或 None）。

    返回 `None` 表示这局**没有可回放的内容**（0 步）—— 契约 §9：生产里真有这种行，
    那时 `has_replay=false`，前端把按钮置灰并写明原因。

    ⚠️ 本函数**不清空内存**：清空是落库之后的收尾（`server._finalize_match` 在
       `finally` 里调 `reset(room)`），保证"落库失败也不会把录制内容留在房间里"。
    """
    if room is None:
        return None
    if step_count(room) <= 0:
        return None
    payload = build(room)
    if _blob_bytes(payload) > MAX_REPLAY_BYTES:
        payload = _shrink(payload)
    return payload


def blob_bytes(payload) -> int:
    """公开的字节数计算（测试与调用方都用它，避免两处各算一次）。"""
    return _blob_bytes(payload or {})


def deep_size(obj, _seen=None) -> int:
    """对象图的常驻字节数（只算**容器自身**，不重复算共享对象）。

    用来兑现契约 §1 那条内存账（"记录器每局常驻 ≤30 KB"）—— 它是**实测量**，
    不是估算：`sys.getsizeof` 只给容器本身的大小，所以这里沿容器递归累加，
    并用 id 去重（两个步骤共用同一个字符串时只算一次，与真实内存一致）。
    """
    import sys
    if _seen is None:
        _seen = set()
    oid = id(obj)
    if oid in _seen:
        return 0
    _seen.add(oid)
    size = sys.getsizeof(obj, 0)
    if isinstance(obj, dict):
        for k, v in obj.items():
            size += deep_size(k, _seen) + deep_size(v, _seen)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for item in obj:
            size += deep_size(item, _seen)
    return size


# ---------------------------------------------------------------------------
# 保留策略 / 权限的**客户端**辅助（判定在 db.py 与 server.py，这里只做纯计算）
# ---------------------------------------------------------------------------
def replay_participants(winner_user_id, loser_user_id):
    """落库时记的"参与者"两列：`{'winner': ..., 'loser': ...}`（无账号为 None）。

    ⚠️ **不能从 `matches.winner_id` 反推**：实测那一列里混着 uuid / `ai-*` /
       游客 sid，长度上无法可靠区分（契约 §2 的理由）。
    """
    return {'winner': winner_user_id or None, 'loser': loser_user_id or None}


def you_are(payload, match_row, viewer_uid):
    """请求者在这条回放里是哪一位：`'p1'` / `'p2'` / `None`（旁观者）。

    ⚠️ **返回的只有代号，绝不下发任何 user_id**（契约 §6）。
       代号口径与 `p1_name` / `p2_name` 完全一致：都来自录制时 `room.players` 的
       插入顺序（= `spectate.seat_order`）。`winner_user_id == viewer_uid` ⇒ `p1`。
       —— 录制时的先手 `p1` 不一定是胜者，但对"你是哪一位"这个用途，
       `p1`/`p2` 只是两块棋盘的标签，不与胜负绑定（前端只拿它分左右）。
    """
    if not viewer_uid or not isinstance(match_row, dict):
        return None
    if match_row.get('winner_user_id') == viewer_uid:
        return 'p1'
    if match_row.get('loser_user_id') == viewer_uid:
        return 'p2'
    return None
