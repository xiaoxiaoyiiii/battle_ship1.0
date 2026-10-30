"""Master-tier AI decision layer (pure functions, no I/O, no socket).

Ported from the legacy ai_brain.py (refactor worktree 740f44f). Ticket #13 keeps
the measured behaviour: the strength of the master tier comes from the
**decision space** (33-card pool, interleaved play, 3 cards per turn, firing on
intel), not from a smarter scorer -- see docs/MASTER_AI_2026_09_21.md.

Two hard contracts, both guarded by the out-of-repo suite:

1. **No cheating.** The functions may read only what a human sitting in that
   seat can see: own hand/ships/attack budget/effect flags, cells *own* recon
   revealed (player.revealed_positions), the opponent's public ship count and
   public shot history, the discard pile, and public log events. They must never
   read opponent.ships / opponent.magic_hand (the card face explicitly reveals a
   hand only for 明智埋葬).

2. **Reproducible randomness.** Every decision uses the caller's RNG, falling
   back to the **module-level random** -- never random.Random(). An unseeded
   Random() draws from OS entropy, so the same seed produced different games
   (lesson #36). Module-level random is what random.seed() (the driver) and the
   rest of the backend share.

Every function is safe on partial state: it must not raise.
"""

from __future__ import annotations

import random
from typing import Any

from ..magic import interaction as interaction_rules
from ..magic.precheck import healing_candidates
from ..magic.rules import (
    lanyu_requirement_reason,
    last_attack_requirement_reason,
    wangyang_requirement_reason,
    woxin_requirement_reason,
)
from ..room import BOARD_SIZE, alive_ships

# ---------------------------------------------------------------------------
# small read-only helpers (public information only)
# ---------------------------------------------------------------------------


def _rng(rng: Any | None = None) -> Any:
    """The RNG for this decision: the caller's, else the **module-level** one.

    Never random.Random(): that is seeded from OS entropy, which made the same
    seed produce different games (lesson #36). The module-level random is the
    same state random.seed() (drivers/tests) and the rest of the backend use, so
    one seed covers placement, RPS, cards and shots.
    """

    return rng if rng is not None else random


def _value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _cell_of(pos: Any) -> tuple[int, int] | None:
    if pos is None:
        return None
    if isinstance(pos, dict):
        x, y = pos.get("x"), pos.get("y")
    elif isinstance(pos, (tuple, list)) and len(pos) >= 2:
        x, y = pos[0], pos[1]
    else:
        x, y = getattr(pos, "x", None), getattr(pos, "y", None)
    if isinstance(x, int) and isinstance(y, int):
        return (x, y)
    return None


def _cells_of(ship: Any) -> set[tuple[int, int]]:
    out = set()
    for position in getattr(ship, "positions", None) or []:
        cell = _cell_of(position)
        if cell is not None:
            out.add(cell)
    return out


def _opponent_id(room: Any, me_id: str) -> str | None:
    for player_id in getattr(room, "players", {}) or {}:
        if player_id != me_id:
            return str(player_id)
    return None


def _attacked_cells(player: Any) -> set[tuple[int, int]]:
    """Cells this player has already fired at (public: both boards show them)."""

    out = set()
    for attack in getattr(player, "attacks", None) or []:
        cell = _cell_of(attack)
        if cell is not None:
            out.add(cell)
    return out


def _known_enemy_cells(player: Any, exclude: frozenset = frozenset()) -> set[tuple[int, int]]:
    """Enemy cells **this player's own recon** revealed (克苏鲁之眼 / 探测雷达).

    Direction matters: players[X].revealed_positions is "what X knows", not
    "where X is exposed" -- the 克苏鲁之眼 branch appends the caster's own ship
    positions to the *opponent's* revealed set. Reading it backwards hands the
    opponent's intel to the wrong side.
    """

    out = set()
    for position in getattr(player, "revealed_positions", None) or []:
        cell = _cell_of(position)
        if cell is not None and cell not in exclude:
            out.add(cell)
    return out


def _all_cells() -> list[tuple[int, int]]:
    return [(x, y) for x in range(BOARD_SIZE) for y in range(BOARD_SIZE)]


# ---------------------------------------------------------------------------
# enemy-cell model
# ---------------------------------------------------------------------------
# Ships are single-cell (6 ships, one cell each), so "which cells cannot hold a
# ship" is everything that can be inferred. There is no ship-shape inference to
# do: a fired-at cell that did not hit is proven empty.


def enemy_cell_model(room: Any, ai_id: str) -> tuple[set, set, set]:
    """Returns (known, safe, unknown) enemy cell sets.

    * known   -- a ship is definitely there (own recon, not fired at yet)
    * safe    -- definitely empty (already fired at: single-cell ships sink)
    * unknown -- neither
    """

    me = (getattr(room, "players", None) or {}).get(ai_id)
    if me is None:
        return set(), set(), set()
    attacked = _attacked_cells(me)
    known = _known_enemy_cells(me, exclude=frozenset(attacked))
    unknown = {cell for cell in _all_cells() if cell not in attacked}
    return known, attacked, unknown


def attack_priority(room: Any, ai_id: str, cell: Any) -> float:
    """Score one cell: higher is better. Unusable input scores -1."""

    try:
        known, safe, _unknown = enemy_cell_model(room, ai_id)
    except Exception:  # noqa: BLE001 - partial state must never raise
        return -1.0
    target = _cell_of(cell)
    if target is None:
        return -1.0
    if target in known:
        return 3.0
    if target in safe:
        return 0.0
    return 1.0


def threatenable_cells(room: Any, ai_id: str) -> set[tuple[int, int]]:
    """Cells that may still hide an enemy ship (known + unknown)."""

    known, _safe, unknown = enemy_cell_model(room, ai_id)
    return known | unknown


# ---------------------------------------------------------------------------
# firing
# ---------------------------------------------------------------------------


def choose_attack(room: Any, ai_id: str, rng: Any | None = None) -> tuple[int, int] | None:
    """Pick a cell to fire at; None when nothing is left to shoot at.

    Rules: (1) fire at a recon-confirmed enemy ship (guaranteed hit); (2) else
    pick uniformly among cells **never fired at**. Firing again into a cell that
    already missed is provably wasted (single-cell ships), which is what the old
    uniform-36 policy did.
    """

    try:
        rng = _rng(rng)
        me = (getattr(room, "players", None) or {}).get(ai_id)
        if me is None:
            return None
        known, _safe, unknown = enemy_cell_model(room, ai_id)
        if known:
            return rng.choice(sorted(known))
        if unknown:
            return rng.choice(sorted(unknown))
        return None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# own ship / placement picks
# ---------------------------------------------------------------------------


def _neighbour_probe_count(probed: set[tuple[int, int]], ship: Any) -> int:
    count = 0
    for (x, y) in _cells_of(ship):
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if (x + dx, y + dy) in probed:
                    count += 1
    return count


def resolve_ship_pick(room: Any, ai_id: str, reason: Any,
                      candidates: Any, rng: Any | None = None) -> Any | None:
    """Answer "pick one of your own ships" for the master seat.

    Sacrifice / exposure reasons pick the ship with the **least information
    value**: the more of its neighbourhood the opponent already bombarded, the
    less a new exposure costs. 守株待兔 (trap_setup) is the opposite goal -- it
    wants the ship most likely to be hit next, so its ranking is the same by
    construction but documented separately: both pick the *most probed*
    neighbourhood, which for a sacrifice is also the least informative one.
    Only the opponent's public shot history is used.
    """

    try:
        rng = _rng(rng)
        cands = [ship for ship in (candidates or []) if ship is not None]
        if not cands:
            return None
        opponent_id = _opponent_id(room, ai_id)
        opponent = (getattr(room, "players", None) or {}).get(opponent_id) if opponent_id else None
        probed = _attacked_cells(opponent) if opponent is not None else set()
        if not probed:
            return rng.choice(cands)
        return cands[max(range(len(cands)),
                         key=lambda i: (_neighbour_probe_count(probed, cands[i]), -i))]
    except Exception:  # noqa: BLE001
        return None


def resolve_placement(room: Any, ai_id: str, kind: Any,
                      candidates: Any, rng: Any | None = None) -> Any | None:
    """Pick a legal cell for a new ship (candidate legality is the caller's job).

    Prefers cells the opponent already fired at: they can never be fired at
    again, so a ship there is safe. Ties break on the lowest index so the choice
    is reproducible.
    """

    try:
        _rng(rng)
        cands = [cell for cell in (candidates or []) if cell is not None]
        if not cands:
            return None
        opponent_id = _opponent_id(room, ai_id)
        opponent = (getattr(room, "players", None) or {}).get(opponent_id) if opponent_id else None
        probed = _attacked_cells(opponent) if opponent is not None else set()

        def safety(cell: Any) -> int:
            target = _cell_of(cell)
            if target is None:
                return -1
            if target in probed:
                return 100
            x, y = target
            return sum(
                1
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if (x + dx, y + dy) in probed
            )

        return cands[max(range(len(cands)), key=lambda i: (safety(cands[i]), -i))]
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# card value table
# ---------------------------------------------------------------------------
# The main tuning surface (docs/MASTER_AI_2026_09_21.md section 7.4). Bands:
#   offence (removes enemy ships)  80-95
#   resources (cards)              55-75
#   defence (shields/revives)      50-70
#   conditional                    base +10, nulled by situational()
#   board resets                   30-45, worth more the further behind you are
#
# The table must cover every card that can be drawn (all but 钢筋铁骨, which is
# hidden and stays out of the deck); an unlisted card would score 0 forever.

CARD_BASE_VALUE: dict[str, int] = {
    # offence
    "轰炸": 92,
    "火力全开": 88,
    "神威！": 85,
    "Freezing！": 85,
    "死者苏生": 85,
    "余音绕梁": 82,
    "滥竽充数": 82,
    "神之宣告": 80,
    "五险一金": 80,
    "硫磺火焰": 80,
    "冻结": 78,
    "无暇圣心": 78,
    "增援": 78,
    "命运骰子": 76,
    "无忧梦呓": 60,
    "极限增援": 75,
    "兵粮寸断": 62,
    "绝处逢生": 75,
    "探测雷达": 74,
    "明智埋葬": 74,
    "看破！": 72,
    "疗愈": 72,
    "守株待兔": 72,
    "无中生有": 70,
    "卧薪尝胆": 70,
    "教皇旨意": 70,
    "桃园结义": 70,
    "溅射": 70,
    "百亿补贴": 68,
    "八方来财": 68,
    "饮血": 68,
    "神机妙算": 68,
    "仁王之盾": 66,
    "越战越勇": 66,
    "盗亦有道": 66,
    "失灵！": 65,
    "亡羊补牢": 65,
    "禁忌果实": 64,
    "雷达子弹": 62,
    "恶魔契约": 62,
    "伊甸园": 60,
    "加百列之光": 60,
    "灵气复苏": 60,
    "平等条约": 58,
    "克苏鲁之眼": 55,
    "回光返照": 45,
    "败者食尘": 40,
}

#: Play only strictly above this; an unplayed card beats a card that would be
#: refunded. Kept at 50 on purpose: 65 was better only for the *old* pool that
#: still held 平等条约 / 加百列之光 in the 58-65 band -- see the measurement
#: table in docs/MASTER_AI_2026_09_21.md section 12.6. Do not move it without
#: re-measuring on the current pool.
PLAY_THRESHOLD = 50

#: Cards per turn. normal/hard play at most one; the master interleaves up to
#: three with shots, which is where most of its decision space comes from.
CARDS_PER_TURN = 3

#: Cards that only make sense right after a hit / a sunk ship.
NEEDS_LAST_HIT = frozenset({"溅射", "雷达子弹"})
NEEDS_LAST_SUNK = frozenset({"越战越勇", "饮血"})


def card_value(name: Any) -> int:
    """Base value of a card name; unlisted cards score 0 (never played)."""

    try:
        return int(CARD_BASE_VALUE.get(str(name or ""), 0))
    except Exception:  # noqa: BLE001
        return 0


def _last_attack(room: Any) -> dict:
    last = getattr(room, "last_attack", None)
    return last if isinstance(last, dict) else {}


def situational(room: Any, ai_id: str, name: str) -> float:
    """Situational multiplier (1.0 = unchanged, 0.0 = never play this now).

    Reads public information only: own ships/hand size, the opponent's shown
    ship count, the last shot's public result, and the intel both seats gained
    from public card effects.
    """

    me = (getattr(room, "players", None) or {}).get(ai_id)
    if me is None:
        return 0.0
    opponent_id = _opponent_id(room, ai_id)
    opponent = (getattr(room, "players", None) or {}).get(opponent_id) if opponent_id else None

    my_ships = int(getattr(me, "remaining_ships", 0) or 0)
    their_ships = int(getattr(opponent, "remaining_ships", 0) or 0) if opponent else 0
    behind = their_ships - my_ships

    last = _last_attack(room)
    if name in NEEDS_LAST_HIT and not last.get("hit"):
        return 0.0
    if name in NEEDS_LAST_SUNK and not last.get("ship_sunk"):
        return 0.0

    multiplier = 1.0

    if name == "卧薪尝胆" and behind <= 0:
        return 0.0

    if name in ("回光返照", "败者食尘"):
        if behind >= 2:
            multiplier *= 1.8
        elif behind <= 0:
            multiplier *= 0.5

    if name in ("轰炸", "神威！", "神之宣告", "硫磺火焰"):
        multiplier *= 1.0 + min(0.4, 0.15 * max(0, behind))
    if name in ("疗愈", "仁王之盾", "卧薪尝胆", "无暇圣心"):
        multiplier *= 1.0 + min(0.4, 0.15 * max(0, -behind))

    hand = len(getattr(me, "magic_hand", None) or [])
    if name in ("无中生有", "八方来财", "亡羊补牢") and hand <= 2:
        multiplier *= 1.5

    if name == "克苏鲁之眼":
        # Both sides expose one ship. With single-cell ships "exposed" means
        # "will be sunk", so it is an information exchange: only worth it when
        # the opponent already knows more about me than I know about them.
        mine_known = len(set(_known_enemy_cells(me)))
        theirs_known = 0
        if opponent is not None:
            theirs_known = len(set(_known_enemy_cells(opponent)))
        if theirs_known <= mine_known:
            multiplier *= 0.35
        else:
            multiplier *= 1.4
        if len(_attacked_cells(me)) >= 20:
            multiplier *= 0.6

    return multiplier


def choose_card(room: Any, ai_id: str, playable: Any,
                rng: Any | None = None) -> int | None:
    """Pick one hand index from the caller's *playable* set; None = hold.

    The caller owns "can it be played at all" (playability + trial-play
    readiness); this only answers "is it worth playing now". A card must score
    **strictly above** PLAY_THRESHOLD: burning a turn on a card that would be
    refunded is worse than holding.
    """

    try:
        me = (getattr(room, "players", None) or {}).get(ai_id)
        if me is None:
            return None
        hand = list(getattr(me, "magic_hand", None) or [])
        best_index, best_value = None, 0.0
        for index in playable or []:
            if not isinstance(index, int) or index < 0 or index >= len(hand):
                continue
            name = str(getattr(hand[index], "name", "") or "")
            value = card_value(name) * situational(room, ai_id, name)
            if value > best_value:
                best_index, best_value = index, value
        if best_index is None or best_value < PLAY_THRESHOLD:
            return None
        return best_index
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# target shapes
# ---------------------------------------------------------------------------
# Three shape sets plus sizes. Keep the sets and the sizes in separate tables:
# merging them (a dict for both) once produced a "dict | set" TypeError inside
# the readiness fallback, which silently made the master play **zero** cards
# (lesson #34).

AREA_CARDS = frozenset({"神威！", "冻结", "探测雷达"})
LINE_CARDS = frozenset({"轰炸"})
CELLS_CARDS = frozenset({"硫磺火焰"})

#: Side length per area card: 神威！/冻结 are 3x3, 探测雷达 is **2x2** (card text
#: and the effect comment agree). A wrong size silently widens the selection.
AREA_SIZE = {"神威！": 3, "冻结": 3, "探测雷达": 2}
DEFAULT_AREA_SIZE = 3

MASTER_TARGET_CARDS = frozenset(AREA_CARDS | LINE_CARDS | CELLS_CARDS)


def is_target_card(name: Any) -> bool:
    return str(name or "") in MASTER_TARGET_CARDS


def _my_ship_cells(room: Any, ai_id: str) -> set[tuple[int, int]]:
    me = (getattr(room, "players", None) or {}).get(ai_id)
    out: set[tuple[int, int]] = set()
    for ship in getattr(me, "ships", None) or []:
        out |= _cells_of(ship)
    return out


def _score_cells(room: Any, ai_id: str, cells: Any, self_harm: bool = False) -> float:
    me = (getattr(room, "players", None) or {}).get(ai_id)
    if me is None:
        return -1.0
    known, safe, _unknown = enemy_cell_model(room, ai_id)
    mine = _my_ship_cells(room, ai_id)
    score = 0.0
    for cell in cells:
        target = _cell_of(cell)
        if target is None:
            continue
        if target in known:
            score += 3.0
        elif target not in safe:
            score += 1.0
        if target in mine:
            score += -20.0 if self_harm else -1.0
    return score


def _score_shenwei_area(room: Any, ai_id: str,
                        cells: Any, board: str) -> float:
    """Score one 神威！ window on either legal board.

    The opponent board is the offensive choice: confirmed enemy cells are
    worth more and untouched cells remain plausible targets.  The self board
    is only useful as a defensive hole, so heavily penalise removing our own
    ships and otherwise leave it below a normal opponent window.  Keeping the
    board choice in the same score comparison prevents the old hard-coded
    ``self`` branch from selecting the AI board every time.
    """

    if board == "opponent":
        return _score_cells(room, ai_id, cells)

    mine = _my_ship_cells(room, ai_id)
    return -20.0 * sum(1 for cell in cells if _cell_of(cell) in mine)


def _area_cells(x: int, y: int, size: int = 3) -> list[tuple[int, int]]:
    return [
        (a, b)
        for a in range(x, x + size)
        for b in range(y, y + size)
        if 0 <= a < BOARD_SIZE and 0 <= b < BOARD_SIZE
    ]


def _window_positions(size: int) -> list[tuple[int, int]]:
    limit = BOARD_SIZE - size
    return [(x, y) for x in range(limit + 1) for y in range(limit + 1)]


def resolve_target(room: Any, ai_id: str, card: Any,
                   rng: Any | None = None) -> dict[str, Any] | None:
    """Choose the target payload for an area / line / cells card.

    Returns None for shapes this decision layer cannot produce; the caller must
    then **not play the card** (playing it would be rejected and refunded,
    wasting the turn's play budget).
    """

    try:
        rng = _rng(rng)
        name = str(getattr(card, "name", card) or "")
        if name in AREA_CARDS:
            size = int(AREA_SIZE.get(name, DEFAULT_AREA_SIZE))
            candidates: list[tuple[float, str, int, int]] = []
            boards = ("self", "opponent") if name == "神威！" else ("opponent",)
            for board in boards:
                for x, y in _window_positions(size):
                    cells = _area_cells(x, y, size)
                    score = _score_shenwei_area(room, ai_id, cells, board)
                    candidates.append((score, board, x, y))
            if not candidates:
                return None
            best_score = max(candidate[0] for candidate in candidates)
            best_candidates = [candidate for candidate in candidates if candidate[0] == best_score]
            _score, board, x, y = rng.choice(best_candidates)
            return {
                "target_area": {"x1": x, "y1": y, "x2": x + size - 1, "y2": y + size - 1},
                "board": board,
            }

        if name in LINE_CARDS:
            best, best_score = None, None
            for index in range(BOARD_SIZE):
                for kind, cells in (
                    ("row", [(x, index) for x in range(BOARD_SIZE)]),
                    ("col", [(index, y) for y in range(BOARD_SIZE)]),
                ):
                    score = _score_cells(room, ai_id, cells)
                    if best_score is None or score > best_score or (score == best_score and rng.random() < 0.5):
                        best, best_score = (kind, index), score
            if best is None:
                return None
            kind, index = best
            return {"target_line": {"type": kind, "index": index}}

        if name in CELLS_CARDS:
            length = 6
            best, best_score = None, None
            for y in range(BOARD_SIZE):
                for x in range(0, BOARD_SIZE - length + 1):
                    cells = [(x + k, y) for k in range(length)]
                    score = _score_cells(room, ai_id, cells)
                    if best_score is None or score > best_score or (score == best_score and rng.random() < 0.5):
                        best, best_score = cells, score
            for x in range(BOARD_SIZE):
                for y in range(0, BOARD_SIZE - length + 1):
                    cells = [(x, y + k) for k in range(length)]
                    score = _score_cells(room, ai_id, cells)
                    if best_score is None or score > best_score or (score == best_score and rng.random() < 0.5):
                        best, best_score = cells, score
            if best is None:
                return None
            return {"target_cells": [{"x": a, "y": b} for a, b in best]}

        return None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# card / value picks ("choose one")
# ---------------------------------------------------------------------------


def resolve_choice(room: Any, ai_id: str, kind: Any, options: Any,
                   rng: Any | None = None) -> Any | None:
    """Answer a "pick one" prompt; the caller supplies the legal options."""

    try:
        opts = list(options or [])
        if not opts:
            return None

        if str(kind) == "lingqi_choice":
            numbers = [int(item) for item in opts if str(item).lstrip("-").isdigit()]
            if not numbers:
                return opts[0]
            me = (getattr(room, "players", None) or {}).get(ai_id)
            mine = int(getattr(me, "remaining_ships", 0) or 0)
            opponent_id = _opponent_id(room, ai_id)
            opponent = (getattr(room, "players", None) or {}).get(opponent_id) if opponent_id else None
            theirs = int(getattr(opponent, "remaining_ships", 0) or 0) if opponent else 0
            want = mine if mine >= theirs else max(1, theirs - 1)
            return min(numbers, key=lambda n: (abs(n - want), n))

        if str(kind) == "shenji_predict":
            numbers = [int(item) for item in opts if str(item).lstrip("-").isdigit()]
            if not numbers:
                return opts[0]
            me = (getattr(room, "players", None) or {}).get(ai_id)
            mine = int(getattr(me, "remaining_ships", 0) or 0)
            incoming = int(getattr(room, "attacks_remaining", 0) or 0)
            want = min(mine, max(0, incoming))
            return min(numbers, key=lambda n: (abs(n - want), n))

        def value_of(option: Any) -> int:
            return card_value(getattr(option, "name", option))

        best = max(range(len(opts)), key=lambda i: (value_of(opts[i]), -i))
        return opts[best]
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# master card pool -- the whitelist, card by card
# ---------------------------------------------------------------------------
# A card may enter the pool only when the AI can (a) produce its target/choice
# inside its own turn and (b) leave **no pending channel** behind. Both are
# tested out of repo (cases/13-ai). Every enabled card carries its own reason;
# every excluded (drawable) card carries the reason it stays out. A future batch
# that "just adds a card because the value table scores it high" would break the
# pending-channel coverage test, which is the point of writing the reasons down.

MASTER_ENABLED_CARDS: dict[str, str] = {
    # (1) no precondition, resolves immediately
    "五险一金": "无需目标；闸门只要求本回合未造成伤害（已造成则判打不了）",
    "看破！": "无需目标；封锁对手本大回合的魔法卡",
    "极限增援": "无需目标；闸门只在自己船少时放行（打平会直接作废）",
    "火力全开": "无需目标；攻击次数翻倍，进战斗时结算",
    "无中生有": "无需目标；双方各摸两张",
    "八方来财": "无需目标；挂持续标记，己方船数主动变化时摸牌",
    "百亿补贴": "无需目标；挂持续标记，沉船累计加攻击次数",
    "无暇圣心": "无需目标；挂两个大回合的胜利判定",
    # (2) need a target shape the decision layer can produce
    "神威！": "3x3，可选自己或对方棋盘；优先选择能命中对方战舰的区域",
    "冻结": "3x3，冻住对方活船，削掉对方下回合的攻击次数",
    "探测雷达": "**2x2** 侦察：显形探到的船，并把无船格记为已排除",
    "轰炸": "整行/整列，可一次击沉多艘",
    "硫磺火焰": "连续 6 格，强制击杀（无视无敌/护盾）",
    # (3) preconditions simple enough to decide exactly
    "守株待兔": "给自己一艘活船挂陷阱（选船走同步代选，不留待办）",
    "盗亦有道": "偷对方刚用过的上一张牌；闸门读连锁栈/历史",
    "加百列之光": "反制正下方那一项或拆场地，不追溯已结算的历史",
    "溅射": "上一发命中后打四邻；条件因子在未命中时把价值归零",
    "雷达子弹": "上一发命中后显形八邻；条件因子在未命中时把价值归零",
    "越战越勇": "刚击沉后 +1 攻击；条件因子在未击沉时把价值归零",
    "饮血": "刚击沉后立刻补抽并挂持续摸牌；条件不成立时价值归零",
    # (4) open pending_placement, and the AI places in place
    "死者苏生": "复活一艘到合法空格；落点由 AI 自己就地选（放置待办当场消费）",
    "增援": "补一艘（不受 6 艘上限）；落点就地选",
    # (5) resolves without any interaction
    "疗愈": "原地复活至多两艘，没有待办",
    # (6) temp_data "pick a card" channel, consumed in place
    "桃园结义": "抽自己船数张、自己挑一张；挑牌待办由 AI 当场回答",
    "亡羊补牢": "从弃牌堆最新 n 张挑一张；挑牌待办当场回答",
    "灵气复苏": "双方按选定的船数重摆；AI 就地摆完自己的棋盘",
    # (7) replace the board and require re-placement; the AI re-places itself
    "滥竽充数": "补满船数（大回合末收回）；放置待办逐个当场消费",
    "回光返照": "清自己棋盘重摆；AI 在同一栈帧内摆完（真人看不到布船屏）",
    "败者食尘": "双方重摆、攻击归零；AI 就地摆完自己那一半",
    # (8) two more with simple preconditions
    "神机妙算": "宣言减少的船数；宣言窗口由 AI 自己回答，不留待办",
    "卧薪尝胆": "给全部活船加盾；闸门只在自己船少时放行",
    # (9) preparation-phase only: the master turn opens a dedicated window
    "余音绕梁": "只能在自己准备阶段打；大师回合为此单独开一次出牌机会",
    "明智埋葬": "埋葬牌堆/对方手里最值的一张；挑牌待办当场回答",
}

#: Cards that can be drawn but must never enter the AI pool.
MASTER_EXCLUDED_CARDS: dict[str, str] = {
    "平等条约": "实测负收益：对手几乎不打改船数的魔法卡，打出去等于白占一次出牌机会",
    "克苏鲁之眼": "要施法者先给出自己那一格的坐标，收益还要等对手回答；实测 +0.0",
    "神之宣告": "两道交互且对自己净亏（死 2 艘换对方 1 艘或一次跳回合）",
    "恶魔契约": "双方绑定：对方沉船自己也要沉，且会给对方开选船交互",
    "教皇旨意": "AI 没有「弃卡换攻击」的逻辑，打出去等于把自己回合清零",
    "伊甸园": "实测 -2.4：把双方攻击次数变成 6-自己船数，领先时反而自废",
    "命运骰子": "摇到 3 点会给双方开弃牌待办；AI 出牌预算不该赌这条延迟链路",
    "无忧梦呓": "延迟到对方回合才拼点；与命运骰子同一形状，且 6/36 平局空过",
    "兵粮寸断": "延迟到对方准备阶段才判定，会留下跨两个大回合的持续状态，未量过",
    "绝处逢生": "实测 -3.4：牺牲全部船后只剩一发，把高胜率换成 1/36 抽奖",
    "仁王之盾": "实测 -0.6：三艘一次性挡伤不如换一张进攻牌（多选通道已接，但收益为负）",
    "Freezing！": "只能在结束阶段打，而 AI 回合没有结束阶段出牌窗口（can_play 会拒）",
    "失灵！": "只用于连锁响应；困难和大师共用反制策略，不主动浪费",
    "禁忌果实": "场地卡，锁住双方非场地魔法；对 AI 是纯限制，未量过收益",
    "钢筋铁骨": "HIDDEN_CARD_NAMES：双方都摸不到，给它做决策没有意义",
}

#: Cards that push room.state to placing_ships. Two of them stacked in one
#: redeploy window leave two markers behind while place_ships consumes them in
#: an if/elif chain, so the second marker is never consumed (measured deadlock).
MASTER_REDEPLOY_CARDS = frozenset({"回光返照", "灵气复苏", "败者食尘"})

#: Cards that read "the caster's own cell" out of the target payload. 克苏鲁之眼
#: is the only one, and it is out of the pool because the decision layer cannot
#: supply that cell -- the guard stays so a future card of this shape must be
#: registered (and given a source) before it can be played.
MASTER_OWN_CELL_CARDS = frozenset({"克苏鲁之眼"})

#: Pending channel each pooled card opens, if any. The AI turn consumes exactly
#: these in place; a pooled card with an unlisted channel is a stall waiting to
#: happen (lesson #38).
CARD_PENDING_CHANNELS: dict[str, tuple[str, ...]] = {
    "守株待兔": ("ship_pick",),
    "桃园结义": ("choice:taoyuan_choice",),
    "亡羊补牢": ("choice:wangyang_choice",),
    "明智埋葬": ("choice:bury_choice",),
    "灵气复苏": ("choice:lingqi_choice", "board_reset"),
    "神机妙算": ("shenji", "placement"),
    "增援": ("placement",),
    "死者苏生": ("placement",),
    "滥竽充数": ("placement",),
    "回光返照": ("board_reset",),
    "败者食尘": ("board_reset",),
}

#: Every channel the AI turn knows how to consume (see services/ai.py). Kept
#: here as data so the pool-coverage test has a single source of truth.
AI_CONSUMED_CHANNELS = frozenset(
    {"placement", "shenji", "board_reset", "ship_pick",
     "choice:taoyuan_choice", "choice:wangyang_choice", "choice:bury_choice",
     "choice:lingqi_choice", "choice:shield_choice"}
)

# ---------------------------------------------------------------------------
# "can this card really resolve right now?" -- the trial-play gate
# ---------------------------------------------------------------------------
# Without this gate the master burned its one play per turn on cards whose
# conditions were only checked at resolution time: 1000 games produced 22393
# refused plays, the win rate *fell* from 48.5% to 41.3% and 17 games deadlocked.
# So: enumerate what the AI could play, drop the ones whose target/conditions
# cannot be produced, and only then score the survivors.
#
# Returns None = "cannot resolve" (drop it) and {} = "no target needed, it can
# resolve". Never test truthiness: {} is a legal answer.


def has_placement_spot(room: Any, ai_id: str) -> bool:
    """Whether at least one legal placement cell exists (same rules as players)."""

    for x in range(BOARD_SIZE):
        for y in range(BOARD_SIZE):
            if interaction_rules.placement_error(room, ai_id, x, y) is None:
                return True
    return False


def card_readiness(room: Any, ai_id: str, card: Any) -> dict[str, Any] | None:
    """Trial-play one card: return its targets payload, or None if it cannot
    resolve now. Only call this for pooled cards (the whitelist owns admission).
    """

    try:
        name = str(getattr(card, "name", "") or "")
        caster = (getattr(room, "players", None) or {}).get(ai_id)
        if caster is None:
            return None
        opponent_id = _opponent_id(room, ai_id)
        opponent = (getattr(room, "players", None) or {}).get(opponent_id) if opponent_id else None
        if opponent is None:
            return None

        # 1. pre-play gates the handler itself enforces (call the real functions,
        #    never a copy: one implementation per rule).
        if getattr(caster, "magic_blocked", None):
            return None
        if _value(getattr(room, "state", "")) == "placing_ships" and (
            name in MASTER_REDEPLOY_CARDS
        ):
            return None
        for gate in (
            last_attack_requirement_reason,
            wangyang_requirement_reason,
            woxin_requirement_reason,
            lanyu_requirement_reason,
        ):
            if gate(room, ai_id, card):
                return None

        # 2. target-shape cards
        if name in MASTER_TARGET_CARDS:
            return resolve_target(room, ai_id, card)

        # 3. per-card preconditions (each written against that card's
        #    success=False branch in domain/magic/effects)
        caster_alive = len(alive_ships(caster))
        opponent_alive = len(alive_ships(opponent))

        if name == "五险一金":
            return {} if int(getattr(caster, "damage_dealt_this_turn", 0) or 0) == 0 else None

        if name == "极限增援":
            # Resolves to "the side with fewer ships wins in two big rounds", so
            # playing it while ahead hands the opponent a winning card.
            return {} if opponent_alive > caster_alive else None

        if name == "克苏鲁之眼":
            # Out of the pool: the caster's own cell cannot be produced here, so
            # the card would die in the caster's own half and be refunded.
            return None

        if name == "守株待兔":
            return {} if caster_alive > 0 else None

        if name in ("死者苏生", "增援", "疗愈"):
            if name in ("死者苏生", "疗愈") and not caster.sunken_ships:
                return None
            if name == "疗愈":
                candidates = list(reversed(healing_candidates(caster)))[:2]
                return {'board': 'self', 'selected_cells': [
                    {'x': ship.positions[0].x, 'y': ship.positions[0].y} for ship in candidates
                ]} if candidates else None
            return {} if has_placement_spot(room, ai_id) else None

        if name == "桃园结义":
            if not (room.magic_deck or []):
                return None
            if caster.effect_flags.no_draw or opponent.effect_flags.no_draw:
                return None
            return {}

        if name == "亡羊补牢":
            return {}

        if name == "灵气复苏":
            return {} if max(caster_alive, opponent_alive) >= 1 else None

        if name == "回光返照":
            if room.attack_order and room.attack_order[0] != ai_id:
                return None
            return {} if opponent_alive - caster_alive >= 2 else None

        if name == "败者食尘":
            return {}

        if name == "滥竽充数":
            return {} if has_placement_spot(room, ai_id) else None

        if name == "神机妙算":
            if (room.magic_temp_data or {}).get("pending_shenji"):
                return None
            return {}

        if name == "卧薪尝胆":
            return {} if caster_alive > 0 else None

        if name == "余音绕梁":
            if _value(getattr(room, "current_phase", "")) != "preparation" or (
                getattr(room, "current_attacker", None) != ai_id
            ):
                return None
            return {}

        if name == "明智埋葬":
            return {} if ((room.magic_deck or []) or (opponent.magic_hand or [])) else None

        if name == "绝处逢生":
            return {} if opponent_alive <= 1 else None

        if name == "仁王之盾":
            return {} if caster_alive > 0 else None

        if name == "盗亦有道":
            if room.chain and getattr(room.chain[-1], "player_id", None) != ai_id:
                return {}
            for entry in reversed(getattr(room, "magic_history", None) or []):
                if entry.get("caster") != ai_id and not entry.get("negated_skip"):
                    return {} if not entry.get("stolen") else None
            return None

        if name == "加百列之光":
            if room.chain:
                return {} if room.chain[-1].player_id != ai_id else None
            if room.field_magic is not None:
                return {}
            return None

        if name == "平等条约":
            # Out of the pool (measured negative). The gate mirrors the card: it
            # only works on the chain item directly below, and only when that
            # item really changes a ship count. Imported locally to keep this
            # module out of the chain module's import cycle.
            from ..magic.chain import equal_treaty_verdict

            if not room.chain:
                return None
            ok, _why = equal_treaty_verdict(room, room.chain[-1])
            return {} if ok else None

        # 4. everything else (all no-precondition cards) can resolve.
        return {}
    except Exception:  # noqa: BLE001 - uncertain means "do not play it"
        # Deliberately conservative, but this is exactly the shape that once hid
        # a TypeError ("dict | set") for a whole batch: a broken gate silently
        # means "the AI never plays anything". The out-of-repo suite counts what
        # the AI actually played, so that cannot pass unnoticed again.
        return None


__all__ = [
    "AI_CONSUMED_CHANNELS",
    "AREA_CARDS",
    "AREA_SIZE",
    "CARD_BASE_VALUE",
    "CARD_PENDING_CHANNELS",
    "CARDS_PER_TURN",
    "CELLS_CARDS",
    "DEFAULT_AREA_SIZE",
    "LINE_CARDS",
    "MASTER_ENABLED_CARDS",
    "MASTER_EXCLUDED_CARDS",
    "MASTER_OWN_CELL_CARDS",
    "MASTER_REDEPLOY_CARDS",
    "MASTER_TARGET_CARDS",
    "NEEDS_LAST_HIT",
    "NEEDS_LAST_SUNK",
    "PLAY_THRESHOLD",
    "attack_priority",
    "card_readiness",
    "card_value",
    "choose_attack",
    "choose_card",
    "enemy_cell_model",
    "has_placement_spot",
    "is_target_card",
    "resolve_choice",
    "resolve_placement",
    "resolve_ship_pick",
    "resolve_target",
    "situational",
    "threatenable_cells",
]
