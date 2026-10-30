"""Battle phase rules: RPS, attack budget, phase ladder and turn switching.

Everything here is pure room mutation; the service layer owns identity checks,
wire frames and the turn watchdog. Attack **effects** (hits, sinking, shields)
belong to ticket #9 and are deliberately absent: this module only decides how
many shots a player gets and when a phase may advance.

Legacy reference: port map 13-domain-rules §2/§3 (server.py:4252-4290,
5755-5840, 5877-5932, 6003-6355, 10969-10987).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

from . import effects
from .room import (
    BOARD_SIZE,
    Player,
    PlayerShip,
    Position,
    Room,
    RoomPhase,
    RoomState,
    alive_ships,
    is_ship_alive,
    opponent_of,
)


def _value(value) -> str:
    """Accept both the enum and the legacy plain string stored by old flows."""

    return getattr(value, "value", value)


RPS_CHOICES: tuple[str, ...] = ("rock", "paper", "scissors")
RPS_BEATS: dict[str, str] = {
    "rock": "scissors",
    "paper": "rock",
    "scissors": "paper",
}

ENTER_BATTLE_ERROR = "无法进入战斗阶段"
ENTER_END_ERROR = "当前不是你的战斗阶段"
ATTACKS_LEFT_ERROR = "你还有剩余攻击次数，无法进入结束阶段"
END_TURN_ERROR = "无法结束当前回合"
CHAIN_BUSY_ERROR = "连锁结算中，请等待响应窗口结束后再结束回合"


@dataclass(frozen=True)
class RpsOutcome:
    status: Literal["win", "tie"]
    message: str
    winner: str | None = None
    loser: str | None = None
    choices: dict[str, str] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Legacy `RPSResult.to_dict` shape, key for key."""

        return {
            "status": self.status,
            "message": self.message,
            "winner": self.winner,
            "loser": self.loser,
            "choices": self.choices,
            "order": self.order,
        }


@dataclass(frozen=True)
class TurnEnd:
    """Outcome of a legal `end_turn`."""

    kind: Literal["next_player", "new_round", "skip_stages"]
    current_attacker: str
    round: int


def resolve_rps(choices: dict[str, str], players: Sequence[str]) -> RpsOutcome:
    """Pure RPS resolution. Ties (including invalid stored values) clear nothing
    here; the service resets `rps_choices`/`rps_processed` exactly like legacy."""

    first, second = players[0], players[1]
    c1, c2 = choices[first], choices[second]

    if c1 == c2:
        return RpsOutcome("tie", "平局，重新猜拳")
    if c1 not in RPS_BEATS or c2 not in RPS_BEATS:
        # Dirty data must never raise KeyError mid-game (legacy fallback).
        return RpsOutcome("tie", "出拳无效，重新猜拳")

    winner, loser = (first, second) if RPS_BEATS[c1] == c2 else (second, first)
    return RpsOutcome(
        status="win",
        message=f"{winner} 获胜",
        winner=winner,
        loser=loser,
        choices={first: c1, second: c2},
        order=[winner, loser],
    )


def frozen_ship_count(player: Player) -> int:
    """Only **living** frozen ships subtract an attack (port map §3.1).

    Dead ships stay in `player.ships`, while `remaining_ships` already excludes
    them; counting a sunk frozen ship again would subtract it twice.
    """

    return sum(1 for ship in alive_ships(player) if getattr(ship, "frozen", None))


def attacks_remaining_for(player: Player) -> int:
    """Attack budget = remaining (alive) ships minus living frozen ships."""

    return max(0, int(player.remaining_ships or 0) - frozen_ship_count(player))


#: Readable alias for callers that ask "how many attacks does this player get?".
attacks_for_player = attacks_remaining_for

def attacks_forced_zero(room: Room) -> bool:
    """Any rule that pins the current attacker's budget to zero (ticket #10).

    Three scopes, deliberately separate (port map 13 section 3.1):
    * zero_attacks_round -- room-wide (败者食尘)
    * zero_attacks_for   -- player / big-round (回光返照), only while they act
    * zero_attacks_turn  -- player / turn (无忧梦呓)
    """

    effects = getattr(room, "game_effects", None)
    if not isinstance(effects, dict):
        return False
    try:
        current_round = int(room.round)
    except (TypeError, ValueError):
        return False
    try:
        if int(effects.get("zero_attacks_round") or -1) == current_round:
            return True
    except (TypeError, ValueError):
        pass
    try:
        entry = effects.get("zero_attacks_for")
        if isinstance(entry, dict):
            if int(entry.get("round") or -1) == current_round and entry.get("player") == room.current_attacker:
                return True
    except (TypeError, ValueError):
        pass
    try:
        turn_entry = effects.get("zero_attacks_turn")
        if isinstance(turn_entry, dict):
            if int(turn_entry.get(room.current_attacker) or -1) == current_round:
                return True
    except (TypeError, ValueError):
        pass
    return False


def recalc_attacker_attacks(room: Room) -> int:
    """Recompute the current attacker's budget under the active field rules.

    Single implementation of the attack-count formula (ticket #11 added the
    field cards to the same path). Covers:
    * papal edict: always 0 (attacks are paid with discarded cards);
    * Eden: 6 - own ships;
    * otherwise own remaining ships minus living frozen ships;
    * plus the 百亿补贴 accumulated bonus, unless a hard-zero rule wins.
    """

    player_id = room.current_attacker
    player = room.players.get(player_id) if player_id else None
    if player is None:
        return int(room.attacks_remaining or 0)
    if attacks_forced_zero(room):
        room.attacks_remaining = 0
        return 0
    from .magic.rules import field_magic_name

    field = field_magic_name(room)
    bonus = int(getattr(player.effect_flags, "subsidy_bonus", 0) or 0)
    if field == "教皇旨意":
        base = 0
    elif field == "伊甸园":
        base = max(0, 6 - int(player.remaining_ships or 0))
    else:
        base = max(0, int(player.remaining_ships or 0) - frozen_ship_count(player))
    room.attacks_remaining = max(0, base + bonus)
    return room.attacks_remaining


def grant_extra_attacks(room: Room, player_id: str, n: int = 1) -> int:
    """Grant extra shots to the current attacker; returns the real delta.

    Field cards and forced-zero rules win: adding to a budget that the rules
    pinned to zero would make those effects look like they did nothing.
    """

    if int(n) <= 0 or room.state != RoomState.ATTACKING:
        return 0
    if room.current_attacker != player_id:
        return 0
    from .magic.rules import field_magic_name

    if attacks_forced_zero(room) or field_magic_name(room) == "教皇旨意":
        return 0
    before = int(room.attacks_remaining or 0)
    room.attacks_remaining = max(0, before + int(n))
    return room.attacks_remaining - before



def attackable_cells(player: Player) -> list[tuple[int, int]]:
    """Cells this player has not fired at yet (the legacy `_attackable_cells`)."""

    attacked = {(attack.x, attack.y) for attack in (player.attacks or [])}
    return [
        (x, y)
        for x in range(BOARD_SIZE)
        for y in range(BOARD_SIZE)
        if (x, y) not in attacked
    ]


def can_enter_end(room: Room, player_id: str) -> bool:
    player = room.players[player_id]
    return room.attacks_remaining <= 0 or not attackable_cells(player)


def phase_transition_error(room: Room, player_id: str, action: str) -> str | None:
    """只读预检；询问前和真正推进时复用同一份阶段规则。"""
    if room.state != RoomState.ATTACKING:
        return ENTER_BATTLE_ERROR if action == 'enter_battle' else ENTER_END_ERROR
    if action == 'enter_battle':
        if room.current_attacker != player_id or _value(room.current_phase) != 'preparation':
            return ENTER_BATTLE_ERROR
    else:
        if room.current_attacker != player_id or _value(room.current_phase) != 'battle':
            return ENTER_END_ERROR
        if room.attacks_remaining > 0 and attackable_cells(room.players[player_id]):
            return ATTACKS_LEFT_ERROR
    return None


def enter_battle(room: Room, player_id: str) -> str | None:
    """preparation -> battle. Returns the legacy error text or None."""

    error = phase_transition_error(room, player_id, 'enter_battle')
    if error:
        return error
    room.current_phase = RoomPhase.BATTLE
    player = room.players[player_id]
    recalc_attacker_attacks(room)
    if player.effect_flags.double_attacks:
        # 火力全开 doubles the budget that already exists (not a recount).
        room.attacks_remaining = max(0, room.attacks_remaining) * 2
        # #38：翻倍即消费租约（旧实现是直接把自己置回 False）。
        effects.consume_flag(room, player_id, "double_attacks")
    return None


def enter_end(room: Room, player_id: str) -> str | None:
    """battle -> end, only when no shot is left or no cell is attackable."""

    error = phase_transition_error(room, player_id, 'enter_end')
    if error:
        return error

    room.current_phase = RoomPhase.END
    # #38：余音绕梁每个结束阶段消耗 1 层（旧实现 -=1，0 即不再有强制击杀）。
    effects.adjust_flag(
        room, player_id, "forced_kill", -1, boundary=effects.BOUNDARY_MATCH
    )
    # 越战越勇在本回合结束阶段失效（旧实现置回 False）。
    effects.consume_flag(room, player_id, "battle_spirit")
    return None


def resolve_turn_end(room: Room, player_id: str) -> TurnEnd | None:
    """end -> opponent preparation, or a new big round back to RPS.

    Skip markers from magic cards are consumed here (they are phase-engine
    state, not card effects): `skip_opponent_turn` skips the opponent's whole
    turn **and flips the round**, `skip_next_turn` skips the next turn, and
    `skip_opponent_stages` skips the opponent inside this big round without
    flipping it.
    """

    if room.current_attacker != player_id or _value(room.current_phase) != "end":
        return None

    order = list(room.attack_order or room.players)
    if player_id not in order:
        return None
    current_index = order.index(player_id)
    next_index = (current_index + 1) % len(order)
    next_attacker = order[next_index]

    if room.skip_opponent_turn and room.skip_opponent_turn == next_attacker:
        room.skip_opponent_turn = None
        next_index = (next_index + 1) % len(order)
        next_attacker = order[next_index]
    if room.skip_next_turn and room.skip_next_turn == next_attacker:
        room.skip_next_turn = None
        next_index = (next_index + 1) % len(order)
        next_attacker = order[next_index]

    skip_stages = False
    if room.skip_opponent_stages and room.skip_opponent_stages == next_attacker:
        room.skip_opponent_stages = None
        skip_stages = True
        next_index = (next_index + 1) % len(order)
        next_attacker = order[next_index]

    if next_index == 0:
        if skip_stages:
            room.current_attacker = next_attacker
            room.current_phase = RoomPhase.PREPARATION
            room.attacks_remaining = 0
            room.state = RoomState.ATTACKING
            return TurnEnd("skip_stages", next_attacker, room.round)

        room.round += 1
        room.state = RoomState.ROCK_PAPER_SCISSORS
        room.rps_choices = {}
        room.rps_processed = False
        room.current_phase = RoomPhase.PREPARATION
        room.skip_opponent_turn = None
        room.skip_next_turn = None
        for seat in room.players.values():
            seat.magic_blocked = False
            seat.magic_blocked_round = None
            seat.damage_dealt_this_turn = 0
            seat.ship_reductions_this_turn = 0
        return TurnEnd("new_round", room.current_attacker, room.round)

    room.current_attacker = next_attacker
    room.current_phase = RoomPhase.PREPARATION
    room.players[next_attacker].damage_dealt_this_turn = 0
    room.players[next_attacker].ship_reductions_this_turn = 0
    recalc_attacker_attacks(room)
    return TurnEnd("next_player", next_attacker, room.round)

# ===========================================================================
# Attack effects (ticket #9)
# ===========================================================================
# Everything below is pure room mutation: no socket emit, no database, no
# asyncio. The service layer turns an AttackOutcome into wire frames and
# settlement. Magic-card side effects (subsidy / trap / demon contract /
# vampire / battle spirit) are injected as hooks by tickets #10-#12; keeping
# them out of this module is what lets the same sink path be reused by normal
# shots, splash and area cards without three drifting copies.

ATTACK_COORDS_INVALID = "非法的攻击坐标"
ATTACK_OUT_OF_BOUNDS = "攻击坐标超出棋盘范围"
ATTACK_NOT_YOUR_TURN = "还没到你的攻击回合"
ATTACK_NOT_BATTLE_PHASE = "当前不是战斗阶段"
ATTACK_CHAIN_BUSY = "连锁结算中，请等待响应窗口结束后再攻击"
ATTACK_NO_ATTACKS = "本回合攻击次数已用尽"
ATTACK_CELL_USED = "你已经攻击过这个位置了"
ATTACK_SHENWEI_HOLE = "该区域已被神威！扣掉，无法攻击"


@dataclass
class AttackOutcome:
    """Result of one legal shot. Payload keys mirror legacy AttackResult."""

    attacker: str
    defender: str
    x: int
    y: int
    hit: bool
    ship_sunk: bool
    shield_blocked: bool
    forced_kill: bool
    invincible: bool
    damage_dealt: bool
    sunk_ship: PlayerShip | None
    remaining_attacks: int
    attacker_remaining_ships: int
    defender_remaining_ships: int
    last_chance: bool = False
    last_stand_win: bool = False
    defender_wiped_out: bool = False

    def to_payload(self) -> dict:
        """Frozen attack_result shape (server.py AttackResult.to_dict)."""

        return {
            "attacker": self.attacker,
            "x": self.x,
            "y": self.y,
            "hit": self.hit,
            "ship_sunk": self.ship_sunk,
            "remaining_attacks": self.remaining_attacks,
            "attacker_remaining_ships": self.attacker_remaining_ships,
            "defender_remaining_ships": self.defender_remaining_ships,
            "shield_blocked": self.shield_blocked,
        }


def normalize_attack_coords(x: Any, y: Any) -> tuple[int, int] | str:
    """Return integer coords or a legacy error message.

    Legacy accepts numeric strings / floats but rejects fractions (1.9 used to
    be truncated to 1, silently firing at another cell) and out-of-board values.
    """

    try:
        fx, fy = float(x), float(y)
    except (TypeError, ValueError):
        return ATTACK_COORDS_INVALID
    if not (fx.is_integer() and fy.is_integer()):
        return ATTACK_COORDS_INVALID
    ix, iy = int(fx), int(fy)
    if not (0 <= ix < BOARD_SIZE and 0 <= iy < BOARD_SIZE):
        return ATTACK_OUT_OF_BOUNDS
    return ix, iy


def cell_in_shenwei_hole(room: Room, player_id: str, x: int, y: int) -> bool:
    for hole in room.game_effects.get("shenwei_holes") or []:
        if not isinstance(hole, dict) or hole.get("player") != player_id:
            continue
        if hole["x1"] <= x <= hole["x2"] and hole["y1"] <= y <= hole["y2"]:
            return True
    return False


def priority_wait_reason(room: Room, player_id: str) -> str | None:
    """The initiator cannot keep acting while the opponent answers a request."""

    pending = room.priority_pending or room.priority_continue
    if not pending:
        return None
    if pending.get('responder') == player_id and room.priority_pending:
        return '请先从阶段转换询问中选择响应或不出牌'
    if pending.get('actor') != player_id:
        return None
    action = {"enter_battle": "进入战斗阶段", "enter_end": "进入结束阶段"}.get(
        pending.get("action"), "阶段转换"
    )
    return f"正在等待对方响应「{action}」，请稍候再操作"


def action_wait_reason(room: Room, player_id: str) -> str | None:
    """Legacy _action_wait_reason: shenji declaration > dice discard > priority."""

    pending = (room.magic_temp_data or {}).get("pending_shenji") or {}
    caster = pending.get("caster") if isinstance(pending, dict) else None
    if caster and caster != player_id:
        return "对方正在宣言神机妙算，请等待宣言完成"
    if (room.pending_dice_discard or {}).get(player_id) is False:
        return "命运骰子生效中，请先选择一张手牌弃置"
    return priority_wait_reason(room, player_id)


def attack_error(room: Room, attacker_id: str, x: Any, y: Any) -> str | None:
    """All legacy attack guards, in the same order as handle_attack."""

    coords = normalize_attack_coords(x, y)
    if isinstance(coords, str):
        return coords
    ix, iy = coords
    if attacker_id != room.current_attacker:
        return ATTACK_NOT_YOUR_TURN
    if _value(room.current_phase) != "battle":
        return ATTACK_NOT_BATTLE_PHASE
    if room.chain or room.chain_waiting or room.chain_resolving:
        return ATTACK_CHAIN_BUSY
    from .magic.interaction import pending_action_reason
    pending = pending_action_reason(room, attacker_id)
    if pending:
        return pending
    wait = action_wait_reason(room, attacker_id)
    if wait:
        return wait
    if room.attacks_remaining <= 0:
        return ATTACK_NO_ATTACKS
    player = room.players[attacker_id]
    if any(cell.x == ix and cell.y == iy for cell in (player.attacks or [])):
        return ATTACK_CELL_USED
    defender_id = opponent_of(room, attacker_id)
    if defender_id and cell_in_shenwei_hole(room, defender_id, ix, iy):
        return ATTACK_SHENWEI_HOLE
    return None


def mark_ship_sunken(player: Player, ship: PlayerShip | None) -> bool:
    """Register a sunk ship once (revive -> sink loops must not duplicate)."""

    if ship is None:
        return False
    if player.sunken_ships is None:
        player.sunken_ships = []
    if ship in player.sunken_ships:
        return False
    player.sunken_ships.append(ship)
    return True


def apply_ship_sunk(
    room: Room, defender_id: str, ship: PlayerShip, *, leave_wreck: bool = True
) -> bool:
    """Core sink bookkeeping shared by every damage source.

    * remaining_ships is the authoritative count (dead ships stay in ships);
    * 留下残骸的沉船只登记一次；残骸被摧毁的战舰不进入可复活列表。
    """

    defender = room.players[defender_id]
    defender.remaining_ships = max(0, int(defender.remaining_ships) - 1)
    if leave_wreck:
        mark_ship_sunken(defender, ship)
    else:
        # 不登记残骸，仍须让击沉订阅者看到该战舰已经死亡。
        ship.hits = list(ship.positions)
        if not any(destroyed is ship for destroyed in defender.permanently_destroyed_ships):
            defender.permanently_destroyed_ships.append(ship)
    return True


def _find_hit_ship(defender: Player, x: int, y: int) -> PlayerShip | None:
    cell = Position(x=x, y=y)
    for ship in defender.ships or []:
        if not is_ship_alive(defender, ship):
            continue
        if cell in (ship.positions or []):
            return ship
    return None


def resolve_attack(room: Room, attacker_id: str, x: int, y: int) -> AttackOutcome:
    """Apply one ordinary shot. Callers must run attack_error first."""

    attacker = room.players[attacker_id]
    defender_id = opponent_of(room, attacker_id)
    assert defender_id is not None
    defender = room.players[defender_id]

    hit = False
    ship_sunk = False
    shield_blocked = False
    forced_kill = bool(attacker.effect_flags.forced_kill)
    invincible = False
    damage_dealt = False
    sunk_ship: PlayerShip | None = None

    target = _find_hit_ship(defender, x, y)
    if target is not None:
        hit = True
        if forced_kill:
            target.hits = list(target.hits or []) + [Position(x=x, y=y)]
            ship_sunk = True
            sunk_ship = target
            apply_ship_sunk(room, defender_id, target)
            damage_dealt = True
        elif target.invincible:
            invincible = True
        elif target.shield:
            target.shield = False
            shield_blocked = True
        else:
            target.hits = list(target.hits or []) + [Position(x=x, y=y)]
            damage_dealt = True
            if len(target.hits) == len(target.positions):
                ship_sunk = True
                sunk_ship = target
                apply_ship_sunk(room, defender_id, target)

    if damage_dealt and "holy_heart" in room.game_effects:
        room.game_effects["holy_heart"]["no_damage"] = False
    if ship_sunk:
        attacker.ship_reductions_this_turn += 1

    outcome = AttackOutcome(
        attacker=attacker_id,
        defender=defender_id,
        x=x,
        y=y,
        hit=hit,
        ship_sunk=ship_sunk,
        shield_blocked=shield_blocked,
        forced_kill=forced_kill,
        invincible=invincible,
        damage_dealt=damage_dealt,
        sunk_ship=sunk_ship,
        remaining_attacks=room.attacks_remaining,
        attacker_remaining_ships=attacker.remaining_ships,
        defender_remaining_ships=defender.remaining_ships,
    )

    if not damage_dealt:
        # A shield / invincible hit is still a shot: spend one attack. The
        # legacy quirk is the opposite for shields: the *cell* is not recorded
        # (so it can be re-shot), but the attack is still spent.
        room.last_attack = {
            "attacker": attacker_id,
            "x": x,
            "y": y,
            "hit": hit,
            "ship_sunk": ship_sunk,
            "round": room.round,
        }
        room.attacks_remaining = max(0, room.attacks_remaining - 1)
        if not shield_blocked:
            attacker.attacks.append(Position(x=x, y=y, hit=hit, ship_sunk=False))
        outcome.remaining_attacks = room.attacks_remaining
        return outcome

    # 回光返照: damaging that caster's ships loses immediately. Legacy returns
    # before recording the shot / spending the attack / emitting attack_result.
    last_chance = room.game_effects.get("last_chance")
    if (
        isinstance(last_chance, dict)
        and last_chance.get("caster") == defender_id
        and last_chance.get("round", room.round) == room.round
    ):
        outcome.last_chance = True
        return outcome

    attacker.damage_dealt_this_turn += 1
    room.last_attack = {
        "attacker": attacker_id,
        "x": x,
        "y": y,
        "hit": hit,
        "ship_sunk": ship_sunk,
        "round": room.round,
    }
    room.attacks_remaining = max(0, room.attacks_remaining - 1)
    attacker.attacks.append(Position(x=x, y=y, hit=hit, ship_sunk=ship_sunk))

    # 绝处逢生: a real kill wins immediately (legacy returns before
    # attack_result and before spending the attack).
    if attacker.effect_flags.last_stand_win and (ship_sunk or forced_kill):
        outcome.last_stand_win = True
        return outcome

    outcome.remaining_attacks = room.attacks_remaining
    outcome.attacker_remaining_ships = attacker.remaining_ships
    outcome.defender_remaining_ships = defender.remaining_ships
    outcome.defender_wiped_out = (
        defender.remaining_ships <= 0 and len(defender.ships or []) > 0
    )
    return outcome


def player_ships_payload(player: Player) -> list[dict[str, Any]]:
    """本人舰船快照；追加陷阱标记，不向对手发送本人舰位。"""

    return [
        {
            "positions": [{"x": pos.x, "y": pos.y} for pos in ship.positions],
            "hits": [],
            "frozen": bool(getattr(ship, "frozen", None)),
            "alive": is_ship_alive(player, ship),
            "shield": bool(getattr(ship, "shield", False)),
            "invincible": bool(getattr(ship, "invincible", False)),
            "trap": bool(getattr(ship, "trap", False)),
        }
        for ship in player.ships
    ]


def dead_ship_count(player: Player) -> int:
    """统计棋盘沉船、移出棋盘的沉船及无残骸的永久死亡战舰，按身份去重。"""

    ships = player.ships or []
    dead: set[int] = set()
    for ship in ships:
        if ship is not None and not is_ship_alive(player, ship):
            dead.add(id(ship))
    for ship in [*(player.sunken_ships or []), *player.permanently_destroyed_ships]:
        if ship is not None and ship not in ships:
            dead.add(id(ship))
    return len(dead)


def took_any_damage(player: Player) -> bool:
    return any(
        bool(ship.hits)
        for ship in [*(player.ships or []), *player.permanently_destroyed_ships]
    )


def match_duration_seconds(room: Room, now: float | None = None) -> int:
    start = room.match_started_at
    if not start:
        return 0
    elapsed = int((now if now is not None else time.time()) - start)
    return elapsed if elapsed > 0 else 0

# ---------------------------------------------------------------------------
# Splash / bomb / sulfur cell rules (reused by the magic layer, ticket #10)
# ---------------------------------------------------------------------------

SPLASH_NEEDS_HIT = "必须在击中对方后使用"


@dataclass
class AreaCellOutcome:
    """One recorded cell from splash / bomb / sulfur."""

    x: int
    y: int
    hit: bool
    ship_sunk: bool
    sunk_ship: PlayerShip | None = None


@dataclass
class AreaStrikeResult:
    cells: list[AreaCellOutcome] = field(default_factory=list)
    ships_sunk: int = 0
    last_chance: bool = False

    @property
    def hit_count(self) -> int:
        return sum(1 for cell in self.cells if cell.hit)


def splash_error(room: Room, caster_id: str) -> str | None:
    last = room.last_attack
    if not isinstance(last, dict) or last.get("attacker") != caster_id:
        return SPLASH_NEEDS_HIT
    if not last.get("hit"):
        return SPLASH_NEEDS_HIT
    return None


def splash_cells(room: Room) -> list[tuple[int, int]]:
    last = room.last_attack or {}
    x, y = int(last.get("x", -1)), int(last.get("y", -1))
    return [
        (nx, ny)
        for nx, ny in ((x, y - 1), (x, y + 1), (x - 1, y), (x + 1, y))
        if 0 <= nx < BOARD_SIZE and 0 <= ny < BOARD_SIZE
    ]


def _area_sink(room: Room, defender_id: str, ship: PlayerShip, *,
               remove_from_ships: bool) -> None:
    defender = room.players[defender_id]
    if remove_from_ships and ship in defender.ships:
        defender.ships.remove(ship)
    apply_ship_sunk(room, defender_id, ship, leave_wreck=not remove_from_ships)


def _mark_area_attack(attacker: Player, x: int, y: int, hit: bool,
                      ship_sunk: bool, flag: str) -> Position:
    position = Position(x=x, y=y, hit=hit, ship_sunk=ship_sunk)
    setattr(position, flag, True)
    attacker.attacks.append(position)
    return position


def resolve_splash(room: Room, caster_id: str) -> AreaStrikeResult:
    """Splash: four orthogonal neighbours; ignores shield/invincibility and
    sinks the whole ship on the first unhit cell. Callers run splash_error."""

    caster = room.players[caster_id]
    defender_id = opponent_of(room, caster_id)
    assert defender_id is not None
    defender = room.players[defender_id]
    result = AreaStrikeResult()

    for x, y in splash_cells(room):
        cell = Position(x=x, y=y)
        hit = False
        sunk_ship: PlayerShip | None = None
        for ship in list(defender.ships or []):
            if not is_ship_alive(defender, ship):
                continue
            if cell in (ship.positions or []) and cell not in (ship.hits or []):
                hit = True
                ship.shield = False
                ship.hits = list(ship.hits or []) + [Position(x=x, y=y)]
                _area_sink(room, defender_id, ship, remove_from_ships=False)
                sunk_ship = ship
                caster.damage_dealt_this_turn += 1
                result.ships_sunk += 1
                if "holy_heart" in room.game_effects:
                    room.game_effects["holy_heart"]["no_damage"] = False
                break
        _mark_area_attack(caster, x, y, hit, sunk_ship is not None, "is_splash")
        result.cells.append(
            AreaCellOutcome(x=x, y=y, hit=hit, ship_sunk=sunk_ship is not None,
                            sunk_ship=sunk_ship)
        )
        if hit:
            last_chance = room.game_effects.get("last_chance")
            if (
                isinstance(last_chance, dict)
                and last_chance.get("caster") == defender_id
                and last_chance.get("round", room.round) == room.round
            ):
                result.last_chance = True
                break
    return result


def line_cells(line_type: str, index: int) -> list[tuple[int, int]]:
    if line_type == "row":
        return [(x, int(index)) for x in range(BOARD_SIZE)]
    return [(int(index), y) for y in range(BOARD_SIZE)]


def resolve_area_strike(room: Room, caster_id: str,
                        cells: list[Any], *, kind: str) -> AreaStrikeResult:
    """Bomb / sulfur: sink every living ship intersecting the selected cells.

    All positions of a sunk ship are recorded as hit cells with is_bomb /
    is_sulfur, and every selected cell that hit nothing is recorded as a miss,
    exactly like the legacy branches.
    """

    flag = "is_bomb" if kind == "bomb" else "is_sulfur"
    caster = room.players[caster_id]
    defender_id = opponent_of(room, caster_id)
    assert defender_id is not None
    defender = room.players[defender_id]
    result = AreaStrikeResult()

    normalized: list[tuple[int, int]] = []
    for raw in cells or []:
        if isinstance(raw, Position):
            x, y = raw.x, raw.y
        elif isinstance(raw, dict):
            x, y = int(raw.get("x")), int(raw.get("y"))
        else:
            x, y = int(raw[0]), int(raw[1])
        if 0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE and (x, y) not in normalized:
            normalized.append((x, y))

    chosen = {Position(x=x, y=y) for x, y in normalized}
    doomed: list[PlayerShip] = []
    for ship in list(defender.ships or []):
        if not is_ship_alive(defender, ship):
            continue
        if any(pos in chosen for pos in (ship.positions or [])):
            doomed.append(ship)

    removed_positions: set[tuple[int, int]] = set()
    for ship in doomed:
        _area_sink(room, defender_id, ship, remove_from_ships=True)
        caster.damage_dealt_this_turn += 1
        result.ships_sunk += 1
        if "holy_heart" in room.game_effects:
            room.game_effects["holy_heart"]["no_damage"] = False
        for pos in ship.positions or []:
            removed_positions.add((pos.x, pos.y))
            _mark_area_attack(caster, pos.x, pos.y, True, True, flag)
            result.cells.append(
                AreaCellOutcome(x=pos.x, y=pos.y, hit=True, ship_sunk=True,
                                sunk_ship=ship)
            )

    for x, y in normalized:
        if (x, y) in removed_positions:
            continue
        _mark_area_attack(caster, x, y, False, False, flag)
        result.cells.append(
            AreaCellOutcome(x=x, y=y, hit=False, ship_sunk=False)
        )
    return result
