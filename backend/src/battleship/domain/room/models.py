"""Room / player / ship state for the rewritten backend.

This module is pure domain: it imports no framework, no database and no socket
library. The shapes follow the legacy `server.py` bodies (GameRoom / Player /
PlayerShip / Position) because those objects are the frozen wire contract for
`game_state` and `room_sync`.

Ticket #7 owns the room skeleton (states, seats, identity keys, reconnect
bookkeeping). Placement / RPS / attack rules stay in ticket #8 and the magic
hand/deck stays in #10; the fields they will consume are initialised here so
that adding a consumer never hits AttributeError.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ...contracts.identity import ai_player_id
from ..effects import EffectState

BOARD_SIZE = 6
DEFAULT_MAX_SHIPS = 6
AI_DIFFICULTIES: tuple[str, ...] = ("easy", "normal", "hard", "master")
LOBBY_ROOM_NAME_MAX_LEN = 20


class RoomState(str, Enum):
    """`waiting → placing_ships → rock_paper_scissors → attacking → game_over`."""

    WAITING = "waiting"
    PLACING_SHIPS = "placing_ships"
    ROCK_PAPER_SCISSORS = "rock_paper_scissors"
    ATTACKING = "attacking"
    GAME_OVER = "game_over"


class RoomPhase(str, Enum):
    PREPARATION = "preparation"
    BATTLE = "battle"
    END = "end"


#: Legal transitions of the room skeleton. The legacy stack sets `room.state`
#: directly in several places (including the deliberate `place_ships` quirk that
#: can drag an attacking room back to RPS, DECISIONS D1); the table documents the
#: intended skeleton and is only enforced by :meth:`Room.transition`.
ROOM_STATE_TRANSITIONS: dict[RoomState, frozenset[RoomState]] = {
    RoomState.WAITING: frozenset({RoomState.PLACING_SHIPS, RoomState.GAME_OVER}),
    RoomState.PLACING_SHIPS: frozenset(
        {RoomState.ROCK_PAPER_SCISSORS, RoomState.GAME_OVER}
    ),
    RoomState.ROCK_PAPER_SCISSORS: frozenset(
        {RoomState.ATTACKING, RoomState.PLACING_SHIPS, RoomState.GAME_OVER}
    ),
    RoomState.ATTACKING: frozenset(
        {RoomState.GAME_OVER, RoomState.ROCK_PAPER_SCISSORS, RoomState.PLACING_SHIPS}
    ),
    RoomState.GAME_OVER: frozenset(),
}


@dataclass
class Position:
    """A board cell. `__eq__` against a dict compares x/y only (legacy behaviour)."""

    x: int
    y: int
    hit: bool = False
    ship_sunk: bool = False
    is_sulfur: bool = False
    is_bomb: bool = False
    is_splash: bool = False
    round: int | None = None

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Position):
            return self.x == other.x and self.y == other.y
        if isinstance(other, dict):
            return self.x == other.get("x") and self.y == other.get("y")
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.x, self.y))


@dataclass
class PlayerShip:
    positions: list[Position] = field(default_factory=list)
    hits: list[Position] = field(default_factory=list)
    invincible: bool = False
    shield: bool = False
    frozen: int | None = None
    trap: Any = False


@dataclass
class EffectFlags:
    """Per-player effect markers (the legacy class attributes become defaults)."""

    treasure_hunter: bool = False
    prediction: bool = False
    subsidy: bool = False
    subsidy_bonus: int = 0
    no_draw: bool = False
    forced_kill: int = 0
    vampire: bool = False
    last_stand: bool = False
    last_stand_win: bool = False
    double_attacks: bool = False
    battle_spirit: bool = False
    wuxian: bool = False


#: Flags that are safe to expose as `active_effects` (same set as the legacy
#: `_PUBLIC_EFFECT_FLAGS`: every bool/int field of EffectFlags).
PUBLIC_EFFECT_FLAGS = frozenset(
    name for name, value in vars(EffectFlags).items()
    if not name.startswith("_") and isinstance(value, (bool, int))
)


@dataclass
class Player:
    name: str | None = None
    user_id: str | None = None
    socket_id: str | None = None
    magic_hand: list[Any] = field(default_factory=list)
    effect_flags: EffectFlags = field(default_factory=EffectFlags)
    ships: list[PlayerShip] = field(default_factory=list)
    attacks: list[Position] = field(default_factory=list)
    remaining_ships: int = 0
    needs_reset: bool = False
    revealed_positions: list[Position] = field(default_factory=list)
    max_ships: int | None = None
    sunken_ships: list[PlayerShip] = field(default_factory=list)
    magic_blocked: bool = False
    # 看破只在施放所在的大回合有效，避免跨大回合残留。
    magic_blocked_round: int | None = None
    # 只在落座时按认证连接写入；单看 user_id 判断不了（自定义房的游客座位键就是 sid）。
    registered: bool = False
    damage_dealt_this_turn: int = 0
    ship_reductions_this_turn: int = 0


def is_ship_alive(player: Player, ship: PlayerShip | None) -> bool:
    """Legacy `_is_ship_alive`: sink only decrements remaining_ships, and dead
    ships stay in `player.ships` so revive cards can find them."""

    if ship is None:
        return False
    if ship in (player.sunken_ships or []):
        return False
    return len(ship.hits or []) < len(ship.positions or [])


def alive_ships(player: Player) -> list[PlayerShip]:
    return [ship for ship in (player.ships or []) if is_ship_alive(player, ship)]


def seat_order(room: "Room") -> list[str]:
    """`room.players` insertion order is the seat order (p1/p2)."""

    return [str(pid) for pid in room.players]


def seat_label(room: "Room", player_id: str | None) -> str:
    if not player_id:
        return "unknown"
    order = seat_order(room)
    pid = str(player_id)
    return f"p{order.index(pid) + 1}" if pid in order else "unknown"


def opponent_of(room: "Room", player_id: str) -> str | None:
    return next((pid for pid in room.players if pid != player_id), None)


def room_match_mode(room: "Room") -> str:
    return "ranked" if bool(getattr(room, "ranked", False)) else "casual"


def field_magic_name(room: "Room") -> str:
    """Public card name of the active field magic (the only implementation).

    The room stores the card *instance* (legacy behaviour); tests and repairs
    may also store a plain dict or a bare name, so all three shapes are accepted
    and an unknown shape degrades to the empty string rather than crashing a
    snapshot. Every other module imports this function; none re-implements it.
    """

    card = getattr(room, "field_magic", None)
    if card is None:
        return ""
    if isinstance(card, str):
        return card
    if isinstance(card, dict):
        return str(card.get("name") or "")
    return str(getattr(card, "name", "") or "")


def rank_payload(room: "Room") -> dict[str, Any]:
    return {"ranked": bool(getattr(room, "ranked", False)), "mode": room_match_mode(room)}


def turn_timing(room: "Room", timeout_seconds: int | None) -> dict[str, int | None]:
    """The single derivation of the client-visible turn countdown.

    The two pieces of truth are exactly the ones the watchdog compares in
    `GameplayService.sweep_timeouts()`: the room's own anchor
    (`turn_started_at`) and the configured timeout. Nothing else stores a
    deadline, so the countdown the player sees cannot drift from the instant
    the server performs its fallback action.

    `turn_deadline` is null whenever no timed turn is running (placement / RPS
    / game over / timeout disabled), which the client renders by hiding the
    timer instead of guessing one.
    """

    timeout = max(0, int(timeout_seconds or 0))
    state = getattr(room.state, "value", room.state)
    started = getattr(room, "turn_started_at", None)
    deadline: int | None = None
    if (
        timeout > 0
        and state == RoomState.ATTACKING.value
        and started is not None
        and room.current_attacker
        and room.turn_timer_attacker == room.current_attacker
    ):
        deadline = int(round((float(started) + timeout) * 1000))
    return {"turn_deadline": deadline, "turn_timeout_seconds": timeout}


def seat_ready(player: "Player" | None) -> bool:
    """A seat is ready once its board is placed (placement rules, not new state)."""

    return player is not None and bool(player.ships)


def opponent_seat_state(room: "Room", player_id: str) -> dict[str, bool]:
    """`opponent_ready` / `opponent_online` from state the room already has.

    Ready = the opponent's board exists; online = a live socket is seated (an
    AI seat is always reachable and never appears in the disconnect table).
    """

    opponent_id = opponent_of(room, player_id)
    opponent = room.players.get(opponent_id) if opponent_id else None
    if opponent is None:
        return {
            "opponent_ready": False,
            "opponent_online": False,
            "opponent_registered": False,
        }
    online = bool(opponent.socket_id) and opponent_id not in (room.disconnected or {})
    if room.is_ai_room and opponent_id == ai_player_id(room.id):
        online = True
    return {
        "opponent_ready": seat_ready(opponent),
        "opponent_online": online,
        "opponent_registered": bool(opponent.registered),
    }


def new_room_id() -> str:
    return str(uuid.uuid4())[:6]


@dataclass
class Room:
    id: str
    created_at: float = field(default_factory=time.time)
    players: dict[str, Player] = field(default_factory=dict)
    state: RoomState = RoomState.WAITING
    name: str = ""
    public: bool = True
    ranked: bool = False
    matchmade: bool = False
    is_ai_room: bool = False
    ai_difficulty: str = "normal"
    ai_difficulty_by_player: dict[str, str] = field(default_factory=dict)

    rps_choices: dict[str, str] = field(default_factory=dict)
    rps_processed: bool = False
    attack_order: list[str] = field(default_factory=list)
    current_attacker: str = ""
    attacks_remaining: int = 0
    round: int = 1
    winner: str = ""
    current_phase: RoomPhase = RoomPhase.PREPARATION

    # Wall-clock anchors for the turn watchdog (ticket #8). `match_started_at`
    # is stamped once when RPS ends and the match really starts; the other two
    # are restarted on every effective action and whenever the attacker changes.
    match_started_at: float | None = None
    turn_started_at: float | None = None
    turn_timer_attacker: str | None = None

    field_magic: Any = None
    field_magic_owner: str | None = None
    magic_history: list[dict[str, Any]] = field(default_factory=list)
    magic_temp_data: dict[str, Any] = field(default_factory=dict)
    #: 待选择项队列（键见 `domain/magic/temps.py`）；激活项仍在 `magic_temp_data`。
    magic_temps: dict[str, Any] = field(default_factory=dict)
    #: 上一次 `temps.finish()` 提升上来的选择项（确认入口读它拼响应，读完即清）。
    magic_promoted: dict[str, Any] | None = None
    magic_discard: list[Any] = field(default_factory=list)
    magic_deck: list[Any] = field(default_factory=list)

    chain: list[Any] = field(default_factory=list)
    #: A resolution is in flight (async card effects yield to the event loop, so
    #: without this latch a second play could interleave with the same stack).
    chain_resolving: bool = False
    chain_waiting: bool = False
    chain_timer: int = -1
    chain_window: str | None = None
    chain_passes: int = 0
    chain_display_token: int | None = None
    chain_display_deadline: float | None = None
    last_attack: Any = None

    game_effects: dict[str, Any] = field(default_factory=dict)
    game_logs: list[dict[str, Any]] = field(default_factory=list)
    replay: dict[str, Any] | None = None

    skip_opponent_turn: Any = None
    skip_next_turn: Any = None
    skip_opponent_stages: Any = None
    huiguang_awaiting_placement: bool = False
    spectate_board_dirty: bool = False

    pending_ship_picks: list[dict[str, Any]] = field(default_factory=list)
    ship_pick_seq: int = 0
    pending_dice_discard: dict[str, bool] = field(default_factory=dict)
    pending_dice_discard_label: dict[str, str] = field(default_factory=dict)
    dice_discard_queue: dict[str, list[str]] = field(default_factory=dict)
    pending_wuyou_dreams: dict[str, int] = field(default_factory=dict)
    pending_bingliang: dict[str, int] = field(default_factory=dict)
    bingliang_skip_draw: dict[str, int] = field(default_factory=dict)

    disconnected: dict[str, dict[str, Any]] = field(default_factory=dict)
    disconnect_seq: int = 0
    reconnect_tokens: dict[str, str] = field(default_factory=dict)
    game_over_reason: str | None = None
    match_id: str | None = None
    # Ticket #9 settlement latch: one room may only be written to the database
    # once (surrender vs disconnect races must not double-count a match).
    # 任务出牌按北京时间日期累计，随对局结算一次入库。
    task_card_uses: dict[str, dict[str, int]] = field(default_factory=dict)
    settled: bool = False
    settlement_result: Any = None

    priority_pending: dict[str, Any] | None = None
    priority_token: int = 0
    priority_continue: dict[str, Any] | None = None
    decline_priority: dict[str, bool] = field(default_factory=dict)

    quick_chat_recent: dict[str, list[float]] = field(default_factory=dict)
    quick_chat_last: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Ticket #31: in-room free-text chat. History is bounded (legacy chat was
    # ephemeral, but a reconnecting seat must not lose what it missed while the
    # socket was down). chat_delivered is the per-seat watermark: a message is
    # only replayed when the seat's socket was not connected when it went out.
    chat_seq: int = 0
    chat_history: list[dict[str, Any]] = field(default_factory=list)
    chat_delivered: dict[str, int] = field(default_factory=dict)
    chat_recent: dict[str, list[float]] = field(default_factory=dict)
    chat_last: dict[str, dict[str, Any]] = field(default_factory=dict)

    spectators: dict[str, dict[str, Any]] = field(default_factory=dict)
    spectate_chat_recent: dict[str, list[float]] = field(default_factory=dict)
    spectate_chat_last: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Ticket #36: 框架无关的 effect 总线运行态（订阅 / 租约 / 事件队列 / 错误）。
    # 只是运行期簿记，不参与房间相等性与 repr，避免日志与快照被噪音污染。
    effects: EffectState = field(default_factory=EffectState, repr=False, compare=False)

    def transition(self, target: RoomState) -> RoomState:
        """Move along the documented skeleton, rejecting impossible jumps.

        Callers that must reproduce a legacy quirk (DECISIONS D1) may assign
        `room.state` directly; product paths should use this method.
        """

        if target not in ROOM_STATE_TRANSITIONS[self.state]:
            raise ValueError(f"非法房间状态转换: {self.state.value} -> {target.value}")
        self.state = target
        return target

    def opponent_of(self, player_id: str) -> str | None:
        return opponent_of(self, player_id)

    def seat_label(self, player_id: str | None) -> str:
        return seat_label(self, player_id)

    def issue_reconnect_token(self, player_id: str) -> str:
        import secrets

        token = secrets.token_hex(16)
        self.reconnect_tokens[player_id] = token
        return token

    def init_player_magic(self, player_id: str) -> None:
        """Reset one hand and create the shared deck on first call (ticket #10).

        The deck is shared by both seats. Hidden cards never enter it, so they
        cannot be drawn even though the card table and effect registry keep them.
        """

        from ..magic.deck import init_shared_deck

        player = self.players.get(player_id)
        if player is not None:
            player.magic_hand = []
        init_shared_deck(self)
