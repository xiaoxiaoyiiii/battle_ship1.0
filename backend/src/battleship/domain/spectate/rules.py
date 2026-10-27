"""Pure spectator rules: event classification, sanitising, snapshots and frames.

Ported from the legacy spectate.py (the single implementation of "what may a
spectator see"). The risk this module exists for is not "the feature is missing"
but "one unclassified event = a wallhack": several room broadcasts carry whole
ship coordinates because they are *public to the two players*, and copying one of
them verbatim to a spectator hands over the board.

Design rules (unchanged from the legacy module):

* default deny -- an event not in SPECTATE_EVENTS never reaches a spectator;
* every event in the frozen outbound inventory must be classified in exactly one
  of SPECTATE_EVENTS / NOT_FOR_SPECTATORS (the external ticket gate asserts the
  coverage; the reasons live here);
* sanitising only removes board information (coordinates, full hands); it must
  keep the action information ("who shot where, hit or miss, who played what"),
  otherwise spectators go from seeing the game to seeing nothing;
* the snapshot and the board frame are whitelist-built -- they never start from
  the private reconnect snapshot (room_sync) and delete fields. One missed delete
  is a leak that raises no error.

Nothing here imports a framework, a database or the socket layer.
"""

from __future__ import annotations

from typing import Any, Iterable

from ...contracts.identity import is_spectate_room, spectate_room_name
from ..room.models import (
    Player,
    Room,
    field_magic_name,
    room_match_mode,
    seat_label,
    seat_order,
)

#: Spectator seats per room (author decision: at most 20).
SPECTATOR_LIMIT = 20

#: One observer-chat line is truncated, never rejected (same rule as game chat).
MAX_SPECTATE_CHAT_LEN = 100

#: Seat label used when a seat key cannot be resolved. Never the raw key.
SEAT_UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Coordinate stripping
# ---------------------------------------------------------------------------
# Any key named here holds coordinates *wherever it appears* in a payload. They
# are removed entirely (not emptied): the legacy leak found in game_log was one
# level deep inside detail, so the walk is recursive.
COORDINATE_KEYS = (
    "positions",
    "sunk_positions",
    "ship_positions",
    "affected_positions",
    "revealed_positions",
    "ships",
    "hits",
)


def _strip_coord_keys(node: Any) -> tuple[Any, int]:
    """Recursively drop coordinate keys; returns (clean copy, dropped cells)."""

    dropped = 0
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in COORDINATE_KEYS:
                if isinstance(value, (list, tuple)):
                    dropped += len(value)
                continue
            cleaned, sub = _strip_coord_keys(value)
            out[key] = cleaned
            dropped += sub
        return out, dropped
    if isinstance(node, (list, tuple)):
        out_list: list[Any] = []
        for value in node:
            cleaned, sub = _strip_coord_keys(value)
            out_list.append(cleaned)
            dropped += sub
        return out_list, dropped
    return node, 0


def _scrub_positions(data: Any) -> tuple[Any, int]:
    return _strip_coord_keys(data)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Per-event sanitisers (pure functions of the serialised payload)
# ---------------------------------------------------------------------------


def _pub_shields_added(data: Any, room: Any = None) -> dict[str, Any] | None:
    """卧薪尝胆: the action is "who gained how many shields", not where ships are."""

    if not isinstance(data, dict):
        return None
    out, _ = _scrub_positions(data)
    out.pop("ships", None)
    out["count"] = _as_int(out.get("count"))
    return out


def _pub_trap_set(data: Any, room: Any = None) -> dict[str, Any] | None:
    """守株待兔: keep who set a trap, drop which ship (its coordinates)."""

    if not isinstance(data, dict):
        return None
    out, _ = _scrub_positions(data)
    return out


def _pub_shield_absorbed(data: Any, room: Any = None) -> dict[str, Any] | None:
    """仁王之盾: the *whole attacked ship's* cells were in the payload."""

    if not isinstance(data, dict):
        return None
    out, _ = _scrub_positions(data)
    return out


def _pub_trap_triggered(data: Any, room: Any = None) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    out, _ = _scrub_positions(data)
    out["sacrificed"] = _as_int(out.get("sacrificed"))
    return out


def _pub_ship_sacrificed(data: Any, room: Any = None) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    out, dropped = _scrub_positions(data)
    # Tell the spectator "a ship of N cells was sacrificed" without the cells.
    out["sacrificed_cells"] = dropped
    return out


def _pub_summary_line(data: Any, room: Any = None) -> dict[str, Any] | None:
    """game_log: text and ownership survive, coordinates never do.

    Real legacy leak: the sacrifice log put the whole sacrificed ship into
    detail.positions. Stripping only the top level would keep it.
    """

    if not isinstance(data, dict):
        return None
    out, _ = _strip_coord_keys(data)
    return out


# ---------------------------------------------------------------------------
# Chain previews: "which area did that card target" is public, the raw targets
# the client submitted are not (their shape is unbounded; it may hold ship ids).
# ---------------------------------------------------------------------------
#: Board ownership per card name. One declaration for the whole project; the
#: legacy frontend mirror is a read-only copy pinned by a test there. "choice"
#: means the server must have validated an explicit board (神威！); a missing or
#: invalid value is *not* a reason to guess "opponent".
AREA_TARGET_BOARDS: dict[str, str] = {
    "神威！": "choice",
    "冻结": "opponent",
    "探测雷达": "opponent",
    "轰炸": "opponent",
    "硫磺火焰": "opponent",
}

BOARD_SIDES = ("self", "opponent")
AREA_TARGET_BOARD_VALUES = BOARD_SIDES + ("choice",)
PREVIEW_SHAPES = ("area", "line", "cells", "single")

#: Public preview keys (whitelist). Must stay disjoint from both forbidden tables.
PREVIEW_KEYS = ("id", "card", "seat", "negated", "preview")
PREVIEW_FIELDS = ("board", "shape", "cells")


def _preview_cells(targets: Any) -> tuple[str, list[tuple[int, int]]] | None:
    """Normalise confirmed targets into (shape, cells); None when unknown.

    Accepts both the raw client target shapes and an already-normalised preview
    body (so sanitising is idempotent).
    """

    if not isinstance(targets, dict):
        return None
    cells: list[tuple[int, int]] = []

    shape = targets.get("shape")
    if shape is not None:
        if shape not in PREVIEW_SHAPES:
            return None
        raw_cells = targets.get("cells")
        if not isinstance(raw_cells, (list, tuple)) or not raw_cells:
            return None
        for cell in raw_cells:
            if not isinstance(cell, dict):
                return None
            try:
                cells.append((int(cell["x"]), int(cell["y"])))
            except (KeyError, TypeError, ValueError):
                return None
        return shape, cells

    area = targets.get("target_area")
    if isinstance(area, dict):
        try:
            x1, y1 = int(area["x1"]), int(area["y1"])
            x2, y2 = int(area["x2"]), int(area["y2"])
        except (KeyError, TypeError, ValueError):
            return None
        for y in range(min(y1, y2), max(y1, y2) + 1):
            for x in range(min(x1, x2), max(x1, x2) + 1):
                cells.append((x, y))
        return ("area", cells) if cells else None

    line = targets.get("target_line")
    if isinstance(line, dict):
        try:
            index = int(line["index"])
        except (KeyError, TypeError, ValueError):
            return None
        if line.get("type") == "row":
            return "line", [(x, index) for x in range(6)]
        if line.get("type") == "col":
            return "line", [(index, y) for y in range(6)]
        return None

    for key in ("target_cells", "selected_cells"):
        raw = targets.get(key)
        if not isinstance(raw, (list, tuple)) or not raw:
            continue
        parsed: list[tuple[int, int]] = []
        for cell in raw:
            if not isinstance(cell, dict):
                return None
            try:
                parsed.append((int(cell["x"]), int(cell["y"])))
            except (KeyError, TypeError, ValueError):
                return None
        return "cells", parsed

    return None


def _preview_id(shape: str, cells: list[tuple[int, int]]) -> str:
    try:
        if shape == "area":
            xs = [cell[0] for cell in cells]
            ys = [cell[1] for cell in cells]
            return "area:%d,%d-%d,%d" % (min(xs), min(ys), max(xs), max(ys))
        if shape == "line":
            first = cells[0]
            kind = "row" if len({cell[1] for cell in cells}) == 1 else "col"
            return "line:%s:%d" % (kind, first[1] if kind == "row" else first[0])
        if shape == "cells" and len(cells) == 1:
            return "single:%d,%d" % cells[0]
        return "cells:%d" % len(cells)
    except (IndexError, TypeError, ValueError):
        return "unknown"


def preview_node(targets: Any, card_name: str | None, room: Any = None,
                 board: str | None = None) -> dict[str, Any] | None:
    """Public area preview for one chain node; None when there is no public area."""

    parsed = _preview_cells(targets)
    if parsed is None:
        return None
    shape, cells = parsed
    if any(not (0 <= x <= 5 and 0 <= y <= 5) for x, y in cells):
        return None

    declared = AREA_TARGET_BOARDS.get(card_name or "")
    if declared is None:
        return None
    side = board if board in BOARD_SIDES else None
    if side is None and declared in BOARD_SIDES:
        side = declared
    if side not in BOARD_SIDES:
        return None

    return {
        "id": _preview_id(shape, cells),
        "card": card_name,
        "seat": seat_label(room, None),
        "board": side,
        "shape": shape,
        "cells": [{"x": x, "y": y} for x, y in cells],
    }


def sanitize_preview_item(item: Any, room: Any = None) -> dict[str, Any] | None:
    """Whitelist-rebuild one serialised chain item (idempotent by design)."""

    if not isinstance(item, dict):
        return None
    card = item.get("card")
    card_name: str | None = None
    if isinstance(card, dict):
        card_name = card.get("name")
    elif isinstance(card, str):
        card_name = card
    if card_name is None:
        card_name = item.get("card_name")

    if item.get("player_id") is None and isinstance(item.get("seat"), str) and item["seat"]:
        seat = item["seat"]
    else:
        seat = seat_label(room, item.get("player_id"))

    node = None
    existing = item.get("preview")
    if isinstance(existing, dict):
        candidate = {
            "shape": existing.get("shape"),
            "cells": existing.get("cells"),
            "board": existing.get("board"),
        }
        if existing.get("card") is None and card_name is not None:
            candidate["card"] = card_name
        node = preview_node(candidate, card_name or existing.get("card"),
                            room=room, board=existing.get("board"))
    if node is None:
        targets = item.get("targets")
        board = targets.get("board") if isinstance(targets, dict) else None
        node = preview_node(targets, card_name, room=room, board=board)
    if node is not None:
        node["seat"] = seat
    return {
        "card": card_name,
        "seat": seat,
        "negated": bool(item.get("negated")),
        "preview": node,
    }


def _pub_magic_chain(data: Any, room: Any = None) -> dict[str, Any] | None:
    """Chain stack: keep who played what, drop raw targets and player_id."""

    if not isinstance(data, dict):
        return None
    chain = data.get("chain")
    if not isinstance(chain, (list, tuple)):
        return {"chain": [], "chain_len": 0, "targets_dropped": 0}
    out: list[dict[str, Any]] = []
    dropped = 0
    for item in chain:
        entry = sanitize_preview_item(item, room=room)
        if entry is None:
            fallback_seat = item.get("seat") if isinstance(item, dict) else None
            entry = {
                "card": None,
                "seat": fallback_seat if isinstance(fallback_seat, str) and fallback_seat
                else seat_label(room, None),
                "negated": False,
                "preview": None,
            }
        if isinstance(item, dict) and isinstance(item.get("targets"), (list, tuple)):
            dropped += len(item["targets"])
        out.append(entry)
    return {"chain": out, "chain_len": len(out), "targets_dropped": dropped}


def _serialize_chain_item(item: Any) -> dict[str, Any]:
    """Turn a live ChainItem (or a dict) into plain data without losing the card name."""

    data = item if isinstance(item, dict) else dict(getattr(item, "__dict__", {}))
    card = data.get("card")
    if card is not None and not isinstance(card, (dict, str)):
        data["card"] = {"name": getattr(card, "name", None)}
    return data


def public_chain(room: Any) -> dict[str, Any]:
    """The one public chain payload (live feed, reconnect and spectate snapshot)."""

    raw = [_serialize_chain_item(item) for item in (getattr(room, "chain", None) or [])]
    return _pub_magic_chain({"chain": raw}, room=room) or {
        "chain": [], "chain_len": 0, "targets_dropped": 0,
    }


# ---------------------------------------------------------------------------
# Board frame (spectate_board): three-level whitelist
# ---------------------------------------------------------------------------
SPECTATE_FRAME_KEYS = frozenset({"room_id", "sides", "seat_labels"})
SPECTATE_FRAME_SIDE_KEYS = frozenset(
    {"seat_id", "name", "remaining_ships", "hand_count", "attacks"}
)
SPECTATE_FRAME_CELL_KEYS = frozenset({"x", "y", "hit", "ship_sunk"})
SPECTATE_FRAME_LABELS = frozenset({"p1", "p2"})


class SpectateFrameError(ValueError):
    """A frame shape that cannot be silently repaired."""


def _canonical_frame_cells(raw_list: Any) -> list[dict[str, Any]]:
    cells = []
    for raw in raw_list or []:
        if not isinstance(raw, dict):
            continue
        x, y = raw.get("x"), raw.get("y")
        if isinstance(x, bool) or isinstance(y, bool):
            continue
        if not isinstance(x, int) or not isinstance(y, int):
            continue
        cells.append(
            {
                key: (bool(raw.get(key)) if key in ("hit", "ship_sunk") else raw[key])
                for key in ("x", "y", "hit", "ship_sunk")
            }
        )
    assert all(set(cell) == set(SPECTATE_FRAME_CELL_KEYS) for cell in cells), \
        "格级白名单写错了（这是实现 bug，不是调用方的问题）"
    return cells


def _canonical_frame_sides(sides: Any) -> dict[str, dict[str, Any]]:
    clean_sides: dict[str, dict[str, Any]] = {}
    for label, side in (sides or {}).items():
        if label not in SPECTATE_FRAME_LABELS or not isinstance(side, dict):
            continue
        clean: dict[str, Any] = {}
        if side.get("seat_id") is not None:
            clean["seat_id"] = str(side["seat_id"])
        if side.get("name") is not None:
            clean["name"] = str(side["name"])
        for key in ("remaining_ships", "hand_count"):
            if key in side:
                value = side[key]
                if isinstance(value, bool) or not isinstance(value, int):
                    continue
                clean[key] = value
        clean["attacks"] = _canonical_frame_cells(side.get("attacks"))
        clean_sides[label] = clean
    assert all(set(side) <= set(SPECTATE_FRAME_SIDE_KEYS)
               for side in clean_sides.values()), \
        "座位级白名单写错了（这是实现 bug，不是调用方的问题）"
    return clean_sides


def _canonical_frame_impl(frame: Any) -> dict[str, Any]:
    if not isinstance(frame, dict):
        return {}
    out: dict[str, Any] = {}
    if frame.get("room_id") is not None:
        out["room_id"] = str(frame["room_id"])
    labels = frame.get("seat_labels")
    if isinstance(labels, dict):
        out["seat_labels"] = {str(key): str(value) for key, value in labels.items()}
    sides = frame.get("sides")
    if isinstance(sides, dict):
        out["sides"] = _canonical_frame_sides(sides)
    return out


def canonical_frame(frame: Any) -> dict[str, Any]:
    """Filter a frame down to the three-level whitelist (never mutates the input)."""

    clean = _canonical_frame_impl(frame)
    assert set(clean) <= set(SPECTATE_FRAME_KEYS), \
        "canonical_frame 自己漏了白名单（这是实现 bug，不是调用方的问题）"
    return clean


def canonical_frame_json(frame: Any, room: Any = None) -> dict[str, Any]:
    """canonical_frame for already-serialised payloads (sanitiser signature)."""

    import json as _json

    try:
        payload = _json.loads(_json.dumps(frame, default=lambda obj: obj.__dict__))
    except (TypeError, ValueError):
        return {}
    return canonical_frame(payload)


CANONICALIZE = frozenset({"spectate_board"})


# ---------------------------------------------------------------------------
# Per-seat public projection (snapshot and frame share this one implementation)
# ---------------------------------------------------------------------------


def player_cells(player: Player | None) -> list[dict[str, Any]]:
    """The cells this seat *shot at* (only ever public, already-hit cells)."""

    cells: list[dict[str, Any]] = []
    if player is None:
        return cells
    for attack in (getattr(player, "attacks", None) or []):
        cells.append(
            {
                "x": getattr(attack, "x", None),
                "y": getattr(attack, "y", None),
                "hit": bool(getattr(attack, "hit", False)),
                "ship_sunk": bool(getattr(attack, "ship_sunk", False)),
            }
        )
    return cells


def side_payload(seat_id: str, player: Player | None) -> dict[str, Any]:
    """One seat's public projection (whitelist; hand contents never included)."""

    return {
        "seat_id": seat_id,
        "name": getattr(player, "name", None),
        "remaining_ships": getattr(player, "remaining_ships", 0),
        "hand_count": len(getattr(player, "magic_hand", None) or []),
        "attacks": player_cells(player),
    }


def build_board_frame(room: Room) -> dict[str, Any]:
    """spectate_board frame.

    sides[label].attacks is in **seat direction** ("what this seat shot at"),
    identical to the snapshot. The client transposes it once; sending board
    direction here would be transposed twice and swap the two boards (legacy
    batch 6 bug, and it raised no error).
    """

    frame: dict[str, Any] = {
        "room_id": room.id,
        "seat_labels": {pid: seat_label(room, pid) for pid in seat_order(room)},
        "sides": {},
    }
    for index, pid in enumerate(seat_order(room)[:2]):
        frame["sides"]["p%d" % (index + 1)] = side_payload(pid, room.players.get(pid))
    return frame


# ---------------------------------------------------------------------------
# Spectator snapshot (whitelist-built; never a filtered room_sync)
# ---------------------------------------------------------------------------
#: Top-level keys of spectate_sync. Recorded legacy capture
#: (fixtures/contract/spectate.json step p3-spectate-join) is the independent
#: source; a missing key blanks part of the spectator screen, an extra key is
#: contract drift.
SPECTATE_SNAPSHOT_KEYS: tuple[str, ...] = (
    "room_id",
    "state",
    "current_phase",
    "current_attacker",
    "attacks_remaining",
    "round",
    "attack_order",
    "ranked",
    "mode",
    "winner",
    "game_over_reason",
    "field_magic",
    "sides",
    "seat_labels",
    "board_attacks",
    "game_logs",
    "chain",
    "shenwei_holes",
    "frozen_area",
    "last_stand_cells",
    "last_stand_owner",
    "spectator_count",
    "spectator_limit",
    "spectators",
)

#: Keys that must never appear at ANY depth of a spectator payload/snapshot.
#: Each one is "if present, the spectator can see the hidden board/hand".
SNAPSHOT_FORBIDDEN_KEYS = (
    "ships",
    "positions",
    "hits",
    "sunk_positions",
    "hand",
    "magic_hand",
    "revealed_positions",
    "effect_flags",
    "active_effects",
    "pending_placement",
    "pending_sacrifice",
    "pending_sacrifice_ships",
    "opponent_attacks",
    "sunk_ships",
    "max_ships",
)


class SpectateSnapshotError(ValueError):
    """A snapshot carrying a hidden-state key -- a leak, never silently repaired."""


def _state_value(value: Any) -> Any:
    return getattr(value, "value", value)


def build_spectate_snapshot(room: Room) -> dict[str, Any]:
    """The one-shot spectate_sync payload for a spectator joining mid-game."""

    seat_ids = seat_order(room)
    labels = {pid: seat_label(room, pid) for pid in seat_ids}

    sides: dict[str, dict[str, Any]] = {}
    for index, pid in enumerate(seat_ids[:2]):
        sides["p%d" % (index + 1)] = side_payload(pid, room.players.get(pid))

    # Each board's "cells already shot at" is the opponent's attack list; this is
    # the transpose of the same data, not a second source.
    board_attacks: dict[str, list[dict[str, Any]]] = {}
    for label in list(sides):
        other = "p2" if label == "p1" else "p1"
        board_attacks[label] = [dict(cell) for cell in sides.get(other, {}).get("attacks", [])]

    effects = room.game_effects if isinstance(room.game_effects, dict) else {}
    logs: list[dict[str, Any]] = []
    for entry in (getattr(room, "game_logs", None) or []):
        cleaned = sanitize_event("game_log", entry, room=room)
        if cleaned is not None:
            logs.append(cleaned)

    spectators = room.spectators or {}
    snapshot = {
        "room_id": room.id,
        "state": _state_value(room.state),
        "current_phase": _state_value(getattr(room, "current_phase", None)),
        "current_attacker": room.current_attacker,
        "attacks_remaining": room.attacks_remaining,
        "round": room.round,
        "attack_order": list(getattr(room, "attack_order", None) or []),
        "ranked": bool(getattr(room, "ranked", False)),
        "mode": room_match_mode(room),
        "winner": getattr(room, "winner", None),
        "game_over_reason": getattr(room, "game_over_reason", None),
        "field_magic": field_magic_name(room),
        "sides": sides,
        "seat_labels": labels,
        "board_attacks": board_attacks,
        "game_logs": logs,
        "chain": public_chain(room),
        "shenwei_holes": [dict(hole) for hole in (effects.get("shenwei_holes") or [])],
        "frozen_area": dict(effects.get("frozen_area") or {}) or None,
        "last_stand_cells": [
            {"x": x, "y": y} for (x, y) in (effects.get("last_stand_cells") or [])
        ],
        "last_stand_owner": effects.get("last_stand_owner"),
        "spectator_count": len(spectators),
        "spectator_limit": SPECTATOR_LIMIT,
        # Names only, and only to other spectators (players see the count only).
        "spectators": [
            {"name": info.get("name"), "joined_at": info.get("joined_at")}
            for info in spectators.values()
        ],
    }
    validate_snapshot(snapshot)
    return snapshot


def _walk_keys(node: Any) -> Iterable[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _walk_keys(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            yield from _walk_keys(value)


def validate_snapshot(snapshot: Any) -> None:
    """Fail loudly on a hidden-state key or a changed top-level shape."""

    if not isinstance(snapshot, dict):
        raise SpectateSnapshotError("spectator snapshot must be a dict")
    if set(snapshot) != set(SPECTATE_SNAPSHOT_KEYS):
        raise SpectateSnapshotError(
            "spectate_sync keys drifted: missing=%s extra=%s"
            % (
                sorted(set(SPECTATE_SNAPSHOT_KEYS) - set(snapshot)),
                sorted(set(snapshot) - set(SPECTATE_SNAPSHOT_KEYS)),
            )
        )
    leaked = sorted(set(_walk_keys(snapshot)) & set(SNAPSHOT_FORBIDDEN_KEYS))
    if leaked:
        raise SpectateSnapshotError("spectator snapshot leaks hidden keys: %s" % leaked)


# ---------------------------------------------------------------------------
# Event classification
# ---------------------------------------------------------------------------
#: Allowed -> sanitiser (None = pass through; the payload carries no secret).
#: Default deny: an event not listed here never reaches a spectator.
SPECTATE_EVENTS: dict[str, Any] = {
    # Core actions and their results (the targeted cell is public by definition).
    "attack_result": None,
    "turn_change": None,
    "turn_skipped": None,
    "phase_updated": None,
    "attacks_updated": None,
    # Chain: the raw client targets are stripped, the public preview is rebuilt.
    "magic_chain_updated": _pub_magic_chain,
    "chain_resolved": None,
    "chain_resolving": None,
    # Play-by-play text: coordinates were really leaked inside detail.
    "game_log": _pub_summary_line,
    "game_message": None,
    # Generic human-readable notice; sometimes a broadcast, sometimes private.
    "message": None,
    "rps_result": None,
    "chat_message": None,
    # Public board markers (announced by the card itself to both players).
    "shenwei_hole": None,
    "shenwei_hole_restored": None,
    "frozen_area": None,
    "last_stand_cells": None,
    "lanyu_recalled": None,
    # Field magic and cross-turn effect badges are public to both players.
    "field_magic_updated": None,
    "reinforcement_activated": None,
    "reinforcement_turn_updated": None,
    "holy_heart_activated": None,
    "holy_heart_interrupted": None,
    "holy_heart_turn_updated": None,
    "dice_rolled": None,
    "dice_discard_complete": None,
    "trap_expired": None,
    "trap_set": _pub_trap_set,
    "trap_triggered": _pub_trap_triggered,
    "shields_added": _pub_shields_added,
    "shield_absorbed": _pub_shield_absorbed,
    "ship_sacrificed": _pub_ship_sacrificed,
    # Match end and settlement announcements (account-level public data).
    "game_over": None,
    "game_canceled": None,
    "opponent_disconnected": None,
    "opponent_reconnected": None,
    "achievements_unlocked": None,
    "xp_gained": None,
    "rank_changed": None,
    # The spectator channel's own events (never mirrored back into itself).
    "spectate_sync": None,
    "spectate_count_changed": None,
    "spectate_ended": None,
    "spectate_roster": None,
    "spectate_joined": None,
    "spectate_left": None,
    "spectate_chat": None,
    "spectate_you": None,
    # The canonical board frame goes through the three-level whitelist filter.
    "spectate_board": canonical_frame_json,
}

#: Explicitly denied, with a reason. An empty reason is a configuration error.
NOT_FOR_SPECTATORS: dict[str, str] = {
    "game_state": "整份局面快照，含 ships[].positions 与对方攻击记录 —— 给了就是透视",
    "room_sync": "重连快照，45 个顶层键含 ships[].positions + hand（最毒的一处）",
    "hand_updated": "手牌**内容**。观众只能看张数，不能看牌面",
    "active_effects": "按座位下发的效果角标，payload 是本方 effect_flags 全量",
    "ships_updated": "本方船只的完整状态（含 positions / hits）",
    "player_ships_updated": "本方船只的完整状态（含 positions / hits）",
    "board_attacks_updated": "本方棋盘上的攻击记录（含 hit/ship_sunk 逐格结果）",
    "revealed_positions": "探测类卡揭示的坐标 —— 那是**付费情报**，不是公开信息",
    "sacrifice_request": "牺牲选船请求：只有当事玩家能回答，观众看到也无法操作",
    "sacrifice_cancelled": "牺牲选船请求的取消（同上）",
    "placement_request": "布船/选格请求：只有当事玩家能回答",
    "placement_done": "布船完成回执（发给当事玩家）",
    "reset_gameboard": "重摆棋盘指令（发给当事玩家，会改他的界面状态）",
    "dice_discard_request": "命运骰子弃牌请求：只有当事玩家能回答",
    "chain_request": "连锁响应请求：只有当事玩家能回答，且会暴露他手上有什么",
    "priority_request": "优先权请求：私有的询问窗口",
    "priority_waiting": "优先权等待态：按座位下发",
    "priority_waiting_end": "优先权等待态解除：按座位下发",
    "priority_setting_updated": "优先权个人设置（账号级偏好，与对局无关）",
    "taoyuan_complete": "桃园结义的选牌回执（发给当事玩家）",
    "lingqi_complete": "灵气复苏的选牌回执（发给当事玩家）",
    "wangyang_complete": "滥竽充数的选牌回执（发给当事玩家）",
    "lingqi_waiting": "灵气复苏的等待态（发给对方）",
    "taoyuan_waiting": "桃园结义的等待态（发给对方）",
    "shenji_waiting": "神机妙算宣言窗口（发给对方）",
    "shenji_waiting_end": "神机妙算宣言窗口结束（发给对方）",
    "match_queued": "匹配队列回执（发给入队者本人）",
    "match_canceled": "取消匹配回执（发给本人）",
    "quick_chat": "局内快捷语（产品需求只要求观众看得到玩家之间的聊天）",
    "lobby_state": "大厅状态（发给在大厅的人；观战者已经不在大厅了）",
    "lobby_hello": "大厅 hello（同上）",
    "lobby_chat": "大厅聊天（不是对局内聊天）",
    "lobby_chat_history": "大厅聊天历史（同上）",
    "resume_game": "断线续玩回执（发给本人）",
    "reconnect_token": "重连令牌 —— **绝对不能**给第三方",
    "reconnect_warning": "重连警告（发给本人）",
    "error": "错误提示：只对发起操作的那个连接有意义",
    # Parameterised friend pushes (legacy helpers, always to=<sid>).
    "friend_request": "好友请求推送（to=<sid> 私人消息）",
    "friend_accepted": "好友通过推送（to=<sid> 私人消息）",
    "friend_invite": "好友邀战推送（to=<sid> 私人消息）",
    "friend_message": "私聊消息推送（to=<sid> 私人消息）",
    "recent_opponent": "最近对手推送（to=<sid> 私人消息）",
}

#: These events' original payload ALWAYS carried ship cells; after sanitising
#: none may remain (the external gate walks them).
MUST_NOT_LEAK_COORDS = (
    "shields_added",
    "shield_absorbed",
    "trap_set",
    "trap_triggered",
    "ship_sacrificed",
)

#: Action fields that MUST survive sanitising (do not over-remove).
MUST_KEEP_ACTION_FIELDS: dict[str, tuple[str, ...]] = {
    "attack_result": ("attacker", "x", "y", "hit"),
    "shields_added": ("player", "count"),
    "shield_absorbed": ("player",),
    "trap_set": ("player",),
    "trap_triggered": ("owner", "sacrificed"),
    "ship_sacrificed": ("player",),
    "game_log": ("ts", "type", "text", "detail"),
    "magic_chain_updated": ("chain", "chain_len"),
}

#: Keys whose presence in a spectator payload is already a leak.
FORBIDDEN_PAYLOAD_KEYS = ("ships", "positions", "hits", "sunk_positions")


# ---------------------------------------------------------------------------
# Import-time self check + entry points
# ---------------------------------------------------------------------------


def _validate() -> None:
    both = set(SPECTATE_EVENTS) & set(NOT_FOR_SPECTATORS)
    if both:
        raise ValueError("事件分类表自相矛盾（既给又不给）：%s" % sorted(both))
    for event, reason in NOT_FOR_SPECTATORS.items():
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("NOT_FOR_SPECTATORS 里的 %r 必须写明理由" % event)
    for event in MUST_NOT_LEAK_COORDS:
        if event not in SPECTATE_EVENTS:
            raise ValueError("%r 被要求'不许泄漏坐标'，却不在 SPECTATE_EVENTS 里" % event)
    for event in MUST_KEEP_ACTION_FIELDS:
        if event not in SPECTATE_EVENTS:
            raise ValueError("%r 被要求'保留动作字段'，却不在 SPECTATE_EVENTS 里" % event)
    stray = set(FORBIDDEN_PAYLOAD_KEYS) - set(SNAPSHOT_FORBIDDEN_KEYS)
    if stray:
        raise ValueError("快照禁字段表漏了事件 payload 的禁字段：%s" % sorted(stray))
    unscrubbed = set(FORBIDDEN_PAYLOAD_KEYS) - set(COORDINATE_KEYS)
    if unscrubbed:
        raise ValueError("COORDINATE_KEYS 漏了：%s" % sorted(unscrubbed))
    for event in CANONICALIZE:
        if event not in SPECTATE_EVENTS:
            raise ValueError("%r 走 canonical_frame，却不在 SPECTATE_EVENTS 里" % event)
        if SPECTATE_EVENTS[event] is None:
            raise ValueError(
                "%r 登记成'原样转发'，但它的 payload 形状不受控 —— 必须走 canonical_frame_json"
                % event
            )
    for card_name, board in AREA_TARGET_BOARDS.items():
        if not isinstance(card_name, str) or not card_name.strip():
            raise ValueError("AREA_TARGET_BOARDS 的键必须是卡名")
        if board not in AREA_TARGET_BOARD_VALUES:
            raise ValueError(
                "AREA_TARGET_BOARDS[%r]=%r 不是合法归属" % (card_name, board)
            )
    for forbidden in (FORBIDDEN_PAYLOAD_KEYS, SNAPSHOT_FORBIDDEN_KEYS):
        overlap = set(PREVIEW_KEYS) & set(forbidden)
        if overlap:
            raise ValueError("预览白名单与禁字段表有交集：%s" % sorted(overlap))
    if not {"card", "seat", "preview"} <= set(PREVIEW_KEYS):
        raise ValueError("PREVIEW_KEYS 漏了必需字段")
    for name, keys in (
        ("SPECTATE_FRAME_KEYS", SPECTATE_FRAME_KEYS),
        ("SPECTATE_FRAME_SIDE_KEYS", SPECTATE_FRAME_SIDE_KEYS),
        ("SPECTATE_FRAME_CELL_KEYS", SPECTATE_FRAME_CELL_KEYS),
    ):
        bad = set(keys) & set(FORBIDDEN_PAYLOAD_KEYS)
        if bad:
            raise ValueError("%s 里出现了禁字段 %s" % (name, sorted(bad)))
    if SPECTATE_FRAME_LABELS != frozenset({"p1", "p2"}):
        raise ValueError("帧只认 p1/p2 两个座位标签")


_validate()


def is_spectatable(event: Any) -> bool:
    """Default deny: only classified events may reach a spectator."""

    return isinstance(event, str) and event in SPECTATE_EVENTS


def sanitize_event(event: Any, data: Any, room: Any = None) -> Any:
    """Return the spectator-safe copy of one event, or None = do not send it."""

    if not is_spectatable(event):
        return None
    sanitiser = SPECTATE_EVENTS[event]
    if sanitiser is None:
        return data
    return sanitiser(data, room)


def can_spectate(allow_a: Any, allow_b: Any) -> bool:
    """Both seats must allow it; unknown (None) degrades to "no".

    A privacy switch must fail towards "nobody can watch" (legacy lesson #21):
    a missed spectator is cheap, one exposed board is not.
    """

    return bool(allow_a) and bool(allow_b)


__all__ = [
    "AREA_TARGET_BOARDS",
    "BOARD_SIDES",
    "CANONICALIZE",
    "COORDINATE_KEYS",
    "FORBIDDEN_PAYLOAD_KEYS",
    "MAX_SPECTATE_CHAT_LEN",
    "MUST_KEEP_ACTION_FIELDS",
    "MUST_NOT_LEAK_COORDS",
    "NOT_FOR_SPECTATORS",
    "PREVIEW_KEYS",
    "SEAT_UNKNOWN",
    "SNAPSHOT_FORBIDDEN_KEYS",
    "SPECTATE_EVENTS",
    "SPECTATE_FRAME_CELL_KEYS",
    "SPECTATE_FRAME_KEYS",
    "SPECTATE_FRAME_LABELS",
    "SPECTATE_FRAME_SIDE_KEYS",
    "SPECTATE_SNAPSHOT_KEYS",
    "SPECTATOR_LIMIT",
    "SpectateFrameError",
    "SpectateSnapshotError",
    "build_board_frame",
    "build_spectate_snapshot",
    "can_spectate",
    "canonical_frame",
    "canonical_frame_json",
    "is_spectate_room",
    "is_spectatable",
    "player_cells",
    "preview_node",
    "public_chain",
    "sanitize_event",
    "sanitize_preview_item",
    "seat_label",
    "seat_order",
    "side_payload",
    "spectate_room_name",
    "validate_snapshot",
]
