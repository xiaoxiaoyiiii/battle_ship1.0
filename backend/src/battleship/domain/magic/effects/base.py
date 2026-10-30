"""Effect contract shared by every magic-card branch.

Effects are pure room mutation plus injected async callbacks. They never import
a framework, a database or a socket library -- that is what lets the service
layer own wire frames, logging and settlement while the card behaviour stays in
one registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from ..cards import MagicCard
from ...room import Player, PlayerShip, Position, Room


@dataclass
class EffectResult:
    success: bool = True
    message: str = ""
    temp_data_id: str | None = None
    game_over: bool = False
    affected_positions: list[Any] = field(default_factory=list)
    #: Extra keys mirrored into the chain_resolved result (cards/max_ships/...).
    extra: dict[str, Any] = field(default_factory=dict)
    #: True = this effect negates the item directly below it on the chain.
    negate_target: bool = False


Emit = Callable[..., Awaitable[None]]
AsyncInt = Callable[[int], Awaitable[Any]]
AsyncNone = Callable[[], Awaitable[None]]
AsyncPlayer = Callable[[str], Awaitable[None]]
AsyncDraw = Callable[[str], Awaitable[Any]]
AsyncSink = Callable[[str, PlayerShip], Awaitable[None]]
AsyncFinish = Callable[[str, str, str], Awaitable[None]]
AsyncShipPick = Callable[[str, str, str, bool, bool], Awaitable[PlayerShip | None]]
AsyncSacrifice = Callable[[str, PlayerShip, str], Awaitable[None]]
AsyncShipDestroyed = Callable[[str, PlayerShip], Awaitable[None]]
AsyncPlacement = Callable[[str, str, int], Awaitable[None]]
AsyncDiceDiscard = Callable[[str, str, str | None, str], Awaitable[None]]
AsyncField = Callable[[MagicCard], Awaitable[None]]
AsyncTearField = Callable[[], Awaitable[MagicCard | None]]
AsyncFrames = Callable[[str, dict[str, Any]], Awaitable[None]]
AsyncReveal = Callable[[str, list[Position], str | None], Awaitable[None]]


@dataclass
class EffectContext:
    room: Room
    caster_id: str
    opponent_id: str
    card: MagicCard
    targets: dict[str, Any]
    emit: Emit
    draw: AsyncDraw
    log: Callable[..., Awaitable[None]]
    finish: AsyncFinish
    sync_ships: AsyncNone
    sync_player_ships: AsyncPlayer
    sync_hand: AsyncPlayer
    sync_active_effects: AsyncNone
    on_ship_sunk: AsyncSink
    notify_treasure: AsyncInt
    grant_attacks: AsyncInt
    maybe_wuxian: Callable[[], Awaitable[bool]]
    request_ship_pick: AsyncShipPick
    sacrifice_ship: AsyncSacrifice
    on_ship_destroyed: AsyncShipDestroyed
    start_placement: AsyncPlacement
    start_dice_discard: AsyncDiceDiscard
    open_shenji: Callable[[str], Awaitable[None]]
    apply_shenji: Callable[[str, int], Awaitable[None]]
    place_field: AsyncField
    tear_down_field: AsyncTearField
    recalc_attacks: Callable[[], Awaitable[None]]
    clear_board_effects: Callable[[list[str], str], Awaitable[None]]
    clear_multiturn_effects: Callable[[str], Awaitable[None]]
    ai_place_board: Callable[[str], Awaitable[bool]]
    emit_board_attacks: Callable[[], Awaitable[None]]
    reveal_to: AsyncReveal
    begin_shenji_redeploy: Callable[[str, int], Awaitable[int]]
    refresh_replay_ships: Callable[[], Awaitable[None]]
    emit_frame: AsyncFrames
    #: Shared dice/shuffle source (module random by default, injectable in tests).
    rng: Any

    @property
    def caster(self) -> Player:
        return self.room.players[self.caster_id]

    @property
    def opponent(self) -> Player:
        return self.room.players[self.opponent_id]

    @property
    def phase(self) -> str:
        return getattr(self.room.current_phase, "value", self.room.current_phase)

    def area(self) -> dict[str, int] | None:
        area = (self.targets or {}).get("target_area")
        return area if isinstance(area, dict) else None

    def line(self) -> dict[str, Any] | None:
        line = (self.targets or {}).get("target_line")
        return line if isinstance(line, dict) else None

    def cells(self, key: str = "target_cells") -> list[dict[str, int]] | None:
        cells = (self.targets or {}).get(key)
        return cells if isinstance(cells, list) else None

    def board_side(self) -> str | None:
        board = (self.targets or {}).get("board")
        return board if board in ("self", "opponent") else None

    def name(self, player_id: str) -> str:
        player = self.room.players.get(player_id)
        return (player.name or player_id) if player else player_id


__all__ = ["EffectContext", "EffectResult"]