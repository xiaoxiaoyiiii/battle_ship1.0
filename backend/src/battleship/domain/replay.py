"""对局回放的**纯模块**：记录器 + 终局打包（ticket #18）。

数据形状（前端唯一契约，见旧栈 docs/REPLAY_2026_09_23.md §2~§6）：

* steps[i]      = {i, kind, actor, text, detail} —— 按行动顺序；
* ships[i]      = {step, p1: [...], p2: [...]} —— 稀疏 + 增量，只在船位真变时记；
* hands[i]      = {step, p1: [...], p2: [...]} —— 稀疏 + 增量；
* attacks[i]    = {step, p1: [...], p2: [...]} —— 稀疏 + 增量，回放棋盘标记的唯一来源；
* effects[i]    = {step, p1: {...}, p2: {...}} —— 稀疏 + 增量，公开效果；
* remaining[i]  = {step, p1: 3, p2: 6}         —— 稀疏 + 增量，权威剩余战舰数；
* board_resets[i] = {step, side}                —— 棋盘重置标记；
* nodes[i]      = {step, kind, label}           —— 服务端算好的进度条关键节点。

铁律：本模块**绝不触碰 socket / 数据库 / 服务层**。回放数据里有双方船位，
一旦进了对局房间就是当场全透视，而且零报错；仓外守卫按 AST 扫本模块。

玩家代号（p1/p2）**只在 build() 里按 room.players 的插入顺序算一次**
（与观战 seat_order 同一口径）；录制期间一律用原始 pid 当键。
"""

from __future__ import annotations

import json

REPLAY_VERSION = 1
MAX_STEPS = 2000
MAX_REPLAY_BYTES = 512 * 1024
_MAX_STEPS = MAX_STEPS
TRUNCATED_TEXT = "此回放被截断"
_ROOM_ATTR = "replay"

#: game_log 的 type -> 回放步骤 kind（只映射一次）。
_KIND_BY_LOG_TYPE = {
    "attack": "attack",
    "magic": "magic",
    "quick_chat": "quick_chat",
    "result": "game_over",
    "system": "system",
    "info": "system",
    "achievements": "system",
    "xp": "system",
    "rank": "system",
}

#: 进度条节点只认这几种。
NODE_KINDS = ("magic", "sunk", "reset", "phase", "game_over", "truncated")

#: 攻击步可剥掉的派生字段（客户端可从 hit/ship_sunk/target 自己算）。
_DETAIL_DERIVED_KEYS = ("shield_blocked",)

#: 六个"没有游戏内日志的行动"。
ACTION_KINDS = (
    "place_ships",
    "rps_choice",
    "enter_battle",
    "enter_end",
    "end_turn",
    "surrender",
)


# ---------------------------------------------------------------------------
# 房间状态（三件齐：初始化 + 消费点 + 回归用例）
# ---------------------------------------------------------------------------
def _state(room):
    """取房间的回放状态；没有就惰性建（Room.replay 字段也有一份）。"""
    st = getattr(room, _ROOM_ATTR, None)
    if isinstance(st, dict):
        return st
    st = {
        "steps": [],
        "ships": [],
        "hands": [],
        "attacks": [],
        "effects": [],
        "remaining": [],
        "board_resets": [],
        "phases": [],
        "rounds": [],
        "chains": [],
        "nodes": [],
        "context": None,
        "lost": {},
        "last": None,
        "last_effects": None,
        "last_attacks": None,
        "last_remaining": None,
        "truncated": None,
    }
    try:
        setattr(room, _ROOM_ATTR, st)
    except Exception:  # noqa: BLE001 - 假房间不许炸
        pass
    return st


def reset(room) -> None:
    """清空这一局的录制状态（终局落库之后）。唯一实现。"""
    if room is None:
        return
    try:
        setattr(room, _ROOM_ATTR, None)
    except Exception:  # noqa: BLE001
        pass


def step_count(room) -> int:
    st = getattr(room, _ROOM_ATTR, None)
    if not isinstance(st, dict):
        return 0
    return len(st.get("steps") or [])


def is_truncated(room):
    st = getattr(room, _ROOM_ATTR, None)
    if not isinstance(st, dict):
        return None
    return st.get("truncated")


# ---------------------------------------------------------------------------
# 座位与稀疏快照
# ---------------------------------------------------------------------------
def _pids(room):
    players = getattr(room, "players", None)
    if isinstance(players, dict):
        return list(players.keys())
    return []


def _side_label(room, pid):
    order = _pids(room)
    try:
        idx = order.index(pid)
    except ValueError:
        return None
    return "p%d" % (idx + 1) if idx < 2 else None


def _is_alive(ship) -> bool:
    """存活判据与全局同一份：len(hits) < len(positions)。"""
    try:
        return len(ship.hits) < len(ship.positions)
    except Exception:  # noqa: BLE001
        return True


def _ship_cells(room, pid, player):
    """该座位全部船格 [{'x','y','alive','sunk'?,'src'}]。

    lost 表（显式登记的主动牺牲）优先于活船列表：同一格最多一条，事实压过推断。
    """
    lost = _lost_cells(room, pid)
    lost_set = set(lost)
    out = []
    for ship in (getattr(player, "ships", None) or []):
        try:
            alive = _is_alive(ship)
            for pos in (getattr(ship, "positions", None) or []):
                x, y = int(pos.x), int(pos.y)
                if (x, y) in lost_set:
                    continue
                cell = {"x": x, "y": y, "alive": alive, "src": "ships"}
                if not alive:
                    cell["sunk"] = True
                out.append(cell)
        except Exception:  # noqa: BLE001
            continue
    for (x, y) in sorted(lost):
        out.append({"x": x, "y": y, "alive": False, "sunk": True, "src": "lost"})
    return out


def _attack_cells(player):
    """该座位打出去的格（Player.attacks 的忠实转写，出界坐标丢掉）。"""
    cells = []
    for a in (getattr(player, "attacks", None) or []):
        try:
            x, y = int(a.x), int(a.y)
        except Exception:  # noqa: BLE001
            continue
        if not (0 <= x <= 5 and 0 <= y <= 5):
            continue
        cell = {"x": x, "y": y}
        if bool(getattr(a, "hit", False)):
            cell["hit"] = True
        if bool(getattr(a, "ship_sunk", False)):
            cell["sunk"] = True
        cells.append(cell)
    return cells


def _attacks_snapshot(room):
    """{pid: ((x, y, hit, sunk), ...)} —— 同一格以列表里最后一条为准。"""
    out = {}
    for pid in _pids(room):
        player = room.players.get(pid)
        if player is None:
            continue
        latest = {}
        order = []
        for cell in _attack_cells(player):
            key = (cell["x"], cell["y"])
            if key not in latest:
                order.append(key)
            latest[key] = (cell["x"], cell["y"], bool(cell.get("hit")), bool(cell.get("sunk")))
        out[pid] = tuple(latest[key] for key in order)
    return out


def _remaining_snapshot(room):
    """{pid: 剩余战舰数} —— 直接读游戏自己的 Player.remaining_ships。"""
    out = {}
    for pid in _pids(room):
        player = room.players.get(pid)
        if player is None:
            continue
        try:
            out[pid] = int(getattr(player, "remaining_ships", 0) or 0)
        except Exception:  # noqa: BLE001
            out[pid] = 0
    return out


def _hand_names(player):
    names = []
    for card in (getattr(player, "magic_hand", None) or []):
        name = getattr(card, "name", None)
        names.append(str(name) if name is not None else str(card))
    return names


def _snapshot(room):
    snap = {}
    for pid in _pids(room):
        player = room.players.get(pid)
        if player is None:
            continue
        snap[pid] = {"ships": _ship_cells(room, pid, player),
                     "hand": _hand_names(player)}
    return snap


# ---------------------------------------------------------------------------
# 主动牺牲掉的船格（牺牲后从 player.ships 移除，但回放里要变红叉）
# ---------------------------------------------------------------------------
def _lost_cells(room, pid):
    st = getattr(room, _ROOM_ATTR, None)
    if not isinstance(st, dict):
        return []
    table = st.get("lost")
    if not isinstance(table, dict):
        return []
    return list(table.get(pid) or [])


def _xy_ints(positions):
    out = []
    seen = set()
    for item in (positions or []):
        try:
            if isinstance(item, dict):
                xy = (int(item["x"]), int(item["y"]))
            else:
                xy = (int(item[0]), int(item[1]))
        except Exception:  # noqa: BLE001
            continue
        if xy in seen:
            continue
        seen.add(xy)
        out.append(xy)
    return out


def _forget_lost_cells(room, pid, positions):
    st = getattr(room, _ROOM_ATTR, None)
    if not isinstance(st, dict):
        return
    table = st.get("lost")
    if not isinstance(table, dict):
        return
    gone = set(_xy_ints(positions))
    if not gone or pid not in table:
        return
    left = [xy for xy in (table.get(pid) or []) if xy not in gone]
    if left:
        table[pid] = left
    else:
        table.pop(pid, None)


def _record_at_current_step(room) -> None:
    """按当前这一步（len(steps)-1）立刻记一次快照；同一步只留一行。"""
    st = _state(room)
    step = len(st.get("steps") or []) - 1
    if step < 0:
        return
    _record_snapshot(room, st, step)
    _merge_same_step_rows(st, step)


def _merge_same_step_rows(st, step) -> None:
    for key in ("ships", "attacks"):
        _merge_same_step_one(st.get(key), step)


def _merge_same_step_one(rows, step) -> None:
    if not isinstance(rows, list) or len(rows) < 2:
        return
    last, prev = rows[-1], rows[-2]
    if not (isinstance(last, dict) and isinstance(prev, dict)):
        return
    if int(last.get("step", -1)) != step or int(prev.get("step", -1)) != step:
        return
    merged = dict(prev)
    merged.update(last)
    rows[-1] = merged
    rows.pop(-2)


def refresh_ships(room) -> None:
    """按当前局面刷新一次稀疏时间线（船位 + 攻击），当前这一步。幂等。"""
    if room is None:
        return
    _record_at_current_step(room)


def note_ship_lost(room, player_id, positions) -> None:
    """登记主动牺牲掉的船格（必须在那一帧的日志之前调用）。"""
    if room is None or not player_id:
        return
    cells = _xy_ints(positions)
    if not cells:
        return
    st = _state(room)
    table = st.get("lost")
    if not isinstance(table, dict):
        table = st["lost"] = {}
    now = list(table.get(player_id) or [])
    known = set(now)
    for xy in cells:
        if xy not in known:
            known.add(xy)
            now.append(xy)
    table[player_id] = now


def note_ship_returned(room, player_id, ship) -> None:
    """船回到棋盘（疗愈 / 死者苏生 / 神机妙算）：撤掉旧格的红叉。

    必须在改这艘船的 positions **之前**调用；调用方收尾时补 refresh_ships。
    """
    if room is None or not player_id or ship is None:
        return
    _forget_lost_cells(room, player_id, [{"x": p.x, "y": p.y}
                                         for p in (getattr(ship, "positions", None) or [])])


def note_board_replaced(room, board_owner_id=None) -> None:
    """棋盘整块换新（灵气复苏 / 败者食尘 / 回光返照）：旧棋盘上的牺牲格作废。"""
    if room is None:
        return
    st = _state(room)
    table = st.get("lost")
    if not isinstance(table, dict):
        table = {}
        st["lost"] = table
    for pid in ([board_owner_id] if board_owner_id else _pids(room)):
        table.pop(pid, None)
    _record_at_current_step(room)


# ---------------------------------------------------------------------------
# 场上公开效果（与观战快照共用同一套字段名）
# ---------------------------------------------------------------------------
_EFFECT_FIELDS = ("shield", "shenwei_holes", "frozen_area",
                  "last_stand_cells", "last_stand_owner")


def _xy_pairs(values):
    out = []
    for item in (values or []):
        try:
            if isinstance(item, dict):
                out.append([int(item["x"]), int(item["y"])])
            else:
                out.append([int(item[0]), int(item[1])])
        except Exception:  # noqa: BLE001
            continue
    return out


def _shield_cells(player):
    out = []
    for ship in (getattr(player, "ships", None) or []):
        try:
            if not getattr(ship, "shield", False):
                continue
            for pos in (getattr(ship, "positions", None) or []):
                out.append([int(pos.x), int(pos.y)])
        except Exception:  # noqa: BLE001
            continue
    out.sort()
    return out


def _effects_of(room, pid):
    player = (getattr(room, "players", None) or {}).get(pid)
    effects = getattr(room, "game_effects", None)
    effects = effects if isinstance(effects, dict) else {}
    player_id = getattr(player, "socket_id", None) or pid
    holes = []
    for hole in (effects.get("shenwei_holes") or []):
        try:
            if hole.get("player") != player_id:
                continue
            holes.append({"x1": int(hole["x1"]), "y1": int(hole["y1"]),
                          "x2": int(hole["x2"]), "y2": int(hole["y2"])})
        except Exception:  # noqa: BLE001
            continue
    frozen = effects.get("frozen_area")
    frozen_out = None
    if isinstance(frozen, dict) and frozen.get("owner") == player_id:
        frozen_out = {"x1": int(frozen["x1"]), "y1": int(frozen["y1"]),
                      "x2": int(frozen["x2"]), "y2": int(frozen["y2"]),
                      "owner": _side_label(room, player_id),
                      "frozen": frozen.get("frozen")}
    owner = effects.get("last_stand_owner")
    out = _empty_effects()
    out["shield"] = _shield_cells(player) if player is not None else []
    out["shenwei_holes"] = holes
    out["frozen_area"] = frozen_out
    if owner == player_id:
        out["last_stand_cells"] = _xy_pairs(effects.get("last_stand_cells"))
        out["last_stand_owner"] = _side_label(room, player_id)
    return out


def _empty_effects():
    return {"shield": [], "shenwei_holes": [], "frozen_area": None,
            "last_stand_cells": [], "last_stand_owner": None}


def _has_any_effect(value) -> bool:
    if not isinstance(value, dict):
        return False
    return bool(value.get("shield") or value.get("shenwei_holes")
                or value.get("frozen_area") or value.get("last_stand_cells")
                or value.get("last_stand_owner"))


def _effects_state(room):
    return {pid: _effects_of(room, pid) for pid in _pids(room)}


def _record_snapshot(room, st, step):
    """与上一次逐字段比对，真变了才各追加一条稀疏 + 增量的时间线。"""
    snap = _snapshot(room)
    last = st.get("last")
    last_effects = st.get("last_effects")
    effects_now = _effects_state(room)

    def _changed(pid, kind_key):
        if last is None:
            return True
        return (last.get(pid) or {}).get(kind_key) != snap[pid][kind_key]

    def _row(kind_key):
        return {"step": step,
                **{side: snap[pid][kind_key]
                   for pid in snap
                   for side in [_side_label(room, pid)]
                   if side and _changed(pid, kind_key)}}

    ships_row = _row("ships")
    hands_row = _row("hand")
    if len(ships_row) > 1:
        st["ships"].append(ships_row)
    if len(hands_row) > 1:
        st["hands"].append(hands_row)

    remaining_now = _remaining_snapshot(room)
    remaining_before = st.get("last_remaining") or {}
    remaining_row = {"step": step}
    for pid, value in remaining_now.items():
        side = _side_label(room, pid)
        if not side:
            continue
        if remaining_before.get(pid) != value:
            remaining_row[side] = value
    if len(remaining_row) > 1:
        st["remaining"].append(remaining_row)

    attacks_now = _attacks_snapshot(room)
    attacks_before = st.get("last_attacks") or {}
    attacks_row = {"step": step}
    for pid, cells in attacks_now.items():
        side = _side_label(room, pid)
        if not side:
            continue
        known = {(cell[0], cell[1]): (cell[2], cell[3])
                 for cell in (attacks_before.get(pid) or ())}
        new_cells = []
        for cell in cells:
            key = (cell[0], cell[1])
            value = (cell[2], cell[3])
            if known.get(key) == value:
                continue
            known[key] = value
            item = {"x": cell[0], "y": cell[1]}
            if cell[2]:
                item["hit"] = True
            if cell[3]:
                item["sunk"] = True
            new_cells.append(item)
        if new_cells:
            attacks_row[side] = new_cells
    if len(attacks_row) > 1:
        st["attacks"].append(attacks_row)

    effects_row = {"step": step}
    changed = []
    for pid, value in effects_now.items():
        side = _side_label(room, pid)
        if not side:
            continue
        before = (last_effects or {}).get(pid) or _empty_effects()
        if before != value:
            effects_row[side] = value
            changed.append((before, value))
    if len(effects_row) > 1 and any(
            _has_any_effect(before) or _has_any_effect(now)
            for (before, now) in changed):
        st["effects"].append(effects_row)

    st["last"] = snap
    st["last_effects"] = effects_now
    st["last_attacks"] = attacks_now
    st["last_remaining"] = remaining_now


# ---------------------------------------------------------------------------
# 上下文（阶段 / 大回合 / 连锁）—— 回放顶栏三项的唯一来源
# ---------------------------------------------------------------------------
def _phase_value(value):
    return str(getattr(value, "value", value) or "")


def _chain_items(room, chain=None):
    """Compact public chain rows: {"card", "side", "negated"}."""
    items = list(chain if chain is not None else (getattr(room, "chain", None) or []))
    out = []
    for item in items:
        card = getattr(item, "card", None)
        name = getattr(card, "name", None)
        if name is None:
            name = getattr(item, "card_name", None)
        if name is None:
            name = str(card) if card is not None else ""
        pid = getattr(item, "player_id", None) or getattr(item, "player", None)
        out.append({
            "card": str(name),
            "side": _side_label(room, pid),
            "negated": bool(getattr(item, "negated", False)),
        })
    return out


def _append_context_row(st, key, field, step, value):
    """Idempotent timeline row: only the last row's value matters."""
    rows = st.setdefault(key, [])
    if rows and rows[-1].get(field) == value:
        return
    rows.append({"step": step, field: value})


def _round_value(value) -> int:
    try:
        return int(value or 1)
    except (TypeError, ValueError):
        return 1


def note_phase(room, phase=None) -> str:
    """Phase of the next recorded step.

    With an explicit phase the value is stamped onto the *next* step (one-shot),
    for callers whose room already moved past the step they are about to record.
    Without one it reads the live room phase. The recorder itself calls this for
    every step, so the timeline and the step stamps share one definition.
    """
    if room is None:
        return ""
    st = _state(room)
    if phase is None:
        return _phase_value(getattr(room, "current_phase", ""))
    text = _phase_value(phase)
    st.setdefault("pending", {})["phase"] = text
    return text


def note_round(room, round_no=None) -> int:
    """Big-round number of the next step (explicit value is one-shot)."""
    if room is None:
        return 1
    st = _state(room)
    if round_no is None:
        return _round_value(getattr(room, "round", 1))
    number = _round_value(round_no)
    st.setdefault("pending", {})["round"] = number
    return number


def note_chain(room, chain=None) -> list:
    """Chain stack of the next step (explicit stack is one-shot).

    Pass the prospective stack when the recorder is fed a card-play step before
    the item is pushed (services/magic.py) so the step carries the stack *after*
    that play; pass an empty list to record that the stack drained. Without an
    argument it reads the live room stack.
    """
    if room is None:
        return []
    st = _state(room)
    if chain is None:
        return _chain_items(room)
    items = _chain_items(room, chain)
    st.setdefault("pending", {})["chain"] = items
    return items


def _step_context(room, st, step):
    """Effective phase/round/chain for one step + its timeline rows."""

    pending = st.get("pending")
    pending = pending if isinstance(pending, dict) else {}
    phase = pending.pop("phase", None)
    if phase is None:
        phase = _phase_value(getattr(room, "current_phase", ""))
    round_no = pending.pop("round", None)
    if round_no is None:
        round_no = _round_value(getattr(room, "round", 1))
    if "chain" in pending:
        chain = pending.pop("chain")
    else:
        chain = _chain_items(room)
    _append_context_row(st, "phases", "phase", step, phase)
    _append_context_row(st, "rounds", "round", step, round_no)
    _append_context_row(st, "chains", "items", step, chain)
    return phase, round_no, chain


def _actor_name(room, pid):
    player = (getattr(room, "players", None) or {}).get(pid)
    name = getattr(player, "name", None) if player is not None else None
    return str(name or pid) if (name or pid) else None


def _step_detail(payload):
    """只留可以 JSON 化的标量/小结构（不复制活对象）。"""
    if not isinstance(payload, dict):
        return {}
    drop = _DETAIL_DERIVED_KEYS if "target" in payload else ()
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
    if kind not in NODE_KINDS:
        return
    st["nodes"].append({"step": step, "kind": kind, "label": str(label)})


def _append(room, kind, text, detail=None, actor=None):
    """所有步骤的唯一追加点：封顶 + 快照 + 关键节点。"""
    st = _state(room)
    step = len(st["steps"])
    if step >= _MAX_STEPS:
        if not st["truncated"]:
            st["truncated"] = "%s（超过 %d 步）" % (TRUNCATED_TEXT, _MAX_STEPS)
            _mark_node(st, step, "truncated", TRUNCATED_TEXT)
        return None
    # 阶段 / 大回合 / 连锁：note_* 是唯一来源，既写时间线行也写步骤标记；
    # 只有真变化才落到步骤上（稀疏），长回放不会因此膨胀。
    phase, round_no, chain = _step_context(room, st, step)
    seen = st.get("context") or {}
    entry = {
        "i": step,
        "kind": str(kind),
        "actor": actor,
        "text": str(text),
        "detail": _step_detail(detail),
    }
    if seen.get("phase") != phase:
        entry["phase"] = phase
    if seen.get("round") != round_no:
        entry["round"] = round_no
    if seen.get("chain") != chain:
        entry["chain"] = chain
    st["context"] = {"phase": phase, "round": round_no, "chain": chain}
    st["steps"].append(entry)
    _record_snapshot(room, st, step)
    _node_from_step(st, step, entry)
    return entry


def _node_from_step(st, step, entry):
    """服务端算一次关键节点（前端不重新推导）。"""
    kind = entry.get("kind")
    detail = entry.get("detail") or {}
    if kind == "magic":
        _mark_node(st, step, "magic", "使用【%s】" % detail.get("card", "魔法卡"))
    elif kind == "attack":
        if detail.get("ship_sunk"):
            target = detail.get("target") or {}
            _mark_node(st, step, "sunk",
                       "击沉战舰 (%s,%s)" % (target.get("x"), target.get("y")))
        elif detail.get("hit"):
            target = detail.get("target") or {}
            _mark_node(st, step, "hit", "命中 (%s,%s)" % (target.get("x"), target.get("y")))
    elif kind == "game_over":
        _mark_node(st, step, "game_over", entry.get("text") or "对局结束")


def note(room, entry) -> None:
    """喂一口游戏内日志（服务层写 room.game_logs 时同步调用，一处覆盖全部记录点）。"""
    if room is None or not isinstance(entry, dict):
        return
    log_type = entry.get("type") or "info"
    detail = entry.get("detail") if isinstance(entry.get("detail"), dict) else {}
    actor_pid = detail.get("attacker") or detail.get("caster") or detail.get("winner")
    _append(room,
            _KIND_BY_LOG_TYPE.get(log_type, "system"),
            entry.get("text") or "",
            detail,
            _actor_name(room, actor_pid) if actor_pid else None)


def note_action(room, kind, label, detail=None, actor=None) -> None:
    """喂一口没有游戏内日志的行动（6 个单一实现点）。绝不往 room.game_logs 加行。"""
    if room is None:
        return
    entry = _append(room, kind, label, detail, actor)
    if entry is not None and kind in ACTION_KINDS:
        _mark_node(_state(room), entry["i"], "phase", str(label))


def note_card_played(room, player_id, card, chained: bool = False) -> None:
    """喂一口「魔法卡出手」—— 入连锁那一刻，不是结算那一刻。"""
    if room is None or card is None:
        return
    actor = _actor_name(room, player_id)
    card_name = str(getattr(card, "name", "") or "魔法卡")
    label = "%s %s【%s】" % (actor, "连锁打出" if chained else "打出", card_name)
    detail = {"card": card_name, "played": True}
    if chained:
        detail["chained"] = True
    _append(room, "magic", label, detail, actor)


def note_hand_change(room, label, detail=None, actor=None) -> None:
    """喂一口改了手牌却没有游戏内日志的选择（回放专用，kind=system）。"""
    if room is None:
        return
    _append(room, "system", label, detail, actor)


def note_board_reset(room, board_owner_id=None) -> None:
    """棋盘重置标记（board_owner_id 为空 = 双方一起重摆）。

    这是标记，不追加步骤；旧棋盘上的沉船格由 note_board_replaced 负责作废。
    """
    if room is None:
        return
    st = _state(room)
    # 旧栈把重置点记在**下一个** step 上（前端 replayComputeFrame 按此消费）。
    step = len(st["steps"])
    targets = [board_owner_id] if board_owner_id else _pids(room)
    for pid in targets:
        side = _side_label(room, pid)
        if side:
            st["board_resets"].append({"step": step, "side": side})
    label = "棋盘重置（%s）" % (_actor_name(room, board_owner_id) if board_owner_id
                                else "双方")
    _mark_node(st, step, "reset", label)


# ---------------------------------------------------------------------------
# 终局打包
# ---------------------------------------------------------------------------
def _blob_bytes(payload) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _trim_timeline(rows, max_step):
    return [row for row in rows if int(row.get("step", -1)) <= max_step]


def _seats_payload(room):
    """{原始 uid: 'p1'|'p2'}（只有真账号进得来）。"""
    seats = {}
    for pid in _pids(room):
        player = (getattr(room, "players", None) or {}).get(pid)
        uid = getattr(player, "user_id", None)
        side = _side_label(room, pid)
        if uid and side:
            seats[str(uid)] = side
    return seats


def build(room):
    """把房间里的录制内容打包成回放 JSON（dict，可 json.dumps）。"""
    st = getattr(room, _ROOM_ATTR, None)
    st = st if isinstance(st, dict) else {}
    order = _pids(room)
    names = {}
    for idx, pid in enumerate(order[:2]):
        player = room.players.get(pid)
        names["p%d" % (idx + 1)] = str(getattr(player, "name", "") or "")

    steps = []
    for entry in list(st.get("steps") or []):
        row = dict(entry)
        sides = row.pop("_side", None)
        if sides:
            row["sides"] = sides
        steps.append(row)

    started_at = 0
    try:
        started_at = int(getattr(room, "match_started_at", 0) or 0)
    except Exception:  # noqa: BLE001
        started_at = 0
    if not started_at:
        try:
            started_at = int(getattr(room, "created_at", 0) or 0)
        except Exception:  # noqa: BLE001
            started_at = 0

    payload = {
        "version": REPLAY_VERSION,
        "p1_name": names.get("p1", ""),
        "p2_name": names.get("p2", ""),
        "seats": _seats_payload(room),
        "started_at": started_at,
        "steps": steps,
        "ships": list(st.get("ships") or []),
        "hands": list(st.get("hands") or []),
        "attacks": list(st.get("attacks") or []),
        "effects": list(st.get("effects") or []),
        "remaining": list(st.get("remaining") or []),
        "board_resets": list(st.get("board_resets") or []),
        "phases": list(st.get("phases") or []),
        "rounds": list(st.get("rounds") or []),
        "chains": list(st.get("chains") or []),
        "nodes": list(st.get("nodes") or []),
        "truncated": st.get("truncated"),
    }
    return payload


def _shrink(payload):
    """blob 超过 MAX_REPLAY_BYTES 时截断并明确标注（绝不静默）。"""
    payload = dict(payload)
    payload["truncated"] = "%s（超过 %d KB）" % (TRUNCATED_TEXT, MAX_REPLAY_BYTES // 1024)
    original_steps = len(payload.get("steps") or [])

    def _too_big(p):
        return _blob_bytes(p) > MAX_REPLAY_BYTES

    while _too_big(payload) and len(payload.get("steps") or []) > 1:
        keep = max(1, len(payload["steps"]) // 2)
        payload["steps"] = payload["steps"][:keep]
        payload["ships"] = _trim_timeline(payload.get("ships") or [], keep)
        payload["hands"] = _trim_timeline(payload.get("hands") or [], keep)
        payload["attacks"] = _trim_timeline(payload.get("attacks") or [], keep)
        payload["effects"] = _trim_timeline(payload.get("effects") or [], keep)
        payload["remaining"] = _trim_timeline(payload.get("remaining") or [], keep)
        payload["board_resets"] = [r for r in (payload.get("board_resets") or [])
                                   if int(r.get("step", 0)) <= keep]
        for key in ("phases", "rounds", "chains"):
            payload[key] = _trim_timeline(payload.get(key) or [], keep)
        payload["nodes"] = [n for n in (payload.get("nodes") or [])
                            if int(n.get("step", 0)) <= keep]

    if _too_big(payload):
        for key in ("ships", "hands", "attacks", "effects", "remaining"):
            rows = payload.get(key) or []
            payload[key] = rows[-1:] if rows else []

    if _too_big(payload):
        payload["nodes"] = (payload.get("nodes") or [])[:200]

    if _too_big(payload):
        payload["steps"] = []
        payload["ships"] = []
        payload["hands"] = []
        payload["attacks"] = []
        payload["effects"] = []
        payload["remaining"] = []
        payload["board_resets"] = []
        payload["phases"] = []
        payload["rounds"] = []
        payload["chains"] = []
        payload["nodes"] = []

    payload["truncated_steps"] = original_steps - len(payload["steps"])
    return payload


def finalize(room):
    """产出最终 JSON 的唯一入口：打包 -> 上限校验 -> dict（或 None）。0 步 = None。"""
    if room is None:
        return None
    if step_count(room) <= 0:
        return None
    payload = build(room)
    if _blob_bytes(payload) > MAX_REPLAY_BYTES:
        payload = _shrink(payload)
    return payload


def blob_bytes(payload) -> int:
    return _blob_bytes(payload or {})


def you_are(payload, match_row, viewer_uid):
    """请求者在这条回放里是哪一位：p1/p2/None（旁观者），只返回代号。"""
    if not viewer_uid or not isinstance(match_row, dict):
        return None
    viewer_uid = str(viewer_uid)
    seats = (payload or {}).get("seats")
    if isinstance(seats, dict):
        side = seats.get(viewer_uid)
        if side in ("p1", "p2"):
            return side
        if viewer_uid not in (str(match_row.get("winner_user_id") or ""),
                              str(match_row.get("loser_user_id") or "")):
            return None
    if match_row.get("winner_user_id") and str(match_row["winner_user_id"]) == viewer_uid:
        return "p1"
    if match_row.get("loser_user_id") and str(match_row["loser_user_id"]) == viewer_uid:
        return "p2"
    return None
