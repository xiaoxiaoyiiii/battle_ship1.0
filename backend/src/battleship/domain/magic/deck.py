"""Shared deck / hand / discard-pile rules (ticket #10).

The deck is **one shared pile for both seats** (legacy `GameRoom.magic_deck`);
each player only owns their hand. Drawing is deterministic under a seeded RNG
so tests and headless simulations are reproducible.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Iterable

from .cards import DECK_CARDS, HIDDEN_CARD_NAMES, MagicCard, card_by_name
from ..room import PlayerShip, Position, Room, is_ship_alive


@dataclass(frozen=True)
class DrawResult:
    """Outcome of one draw; `card is None` means nothing entered the hand."""

    card: MagicCard | None
    duplicate: MagicCard | None = None
    empty: bool = False
    no_draw: bool = False

    @property
    def added(self) -> bool:
        return self.card is not None


def init_shared_deck(
    room: Room,
    cards: Iterable[MagicCard] | None = None,
    *,
    rng: Any | None = None,
) -> None:
    """Create and shuffle the shared deck exactly once per room.

    Hidden cards never enter the deck, so nobody can draw them (they remain in
    the card table / effect registry / front-end codex).
    """

    if room.magic_deck:
        return
    source = list(cards if cards is not None else DECK_CARDS)
    deck = [card for card in source if card.name not in HIDDEN_CARD_NAMES]
    (rng or random).shuffle(deck)
    room.magic_deck = deck


def draw_card(room: Room, player_id: str, *, rng: Any | None = None) -> DrawResult:
    """Draw the top card, applying the frozen duplicate rule.

    A duplicate (same name AND speed, except 「失灵！」) is discarded instead of
    entering the hand; the caller still gets `None` like the legacy method.
    """

    player = room.players.get(player_id)
    if player is None:
        return DrawResult(card=None, empty=True)
    if getattr(player.effect_flags, "no_draw", False):
        return DrawResult(card=None, no_draw=True)
    if not room.magic_deck:
        return DrawResult(card=None, empty=True)

    card = room.magic_deck.pop(0)
    if card.name != "失灵！" and any(
        existing.name == card.name and existing.speed == card.speed
        for existing in player.magic_hand
    ):
        room.magic_discard.append(card)
        return DrawResult(card=None, duplicate=card)

    player.magic_hand.append(card)
    return DrawResult(card=card)


def draw_to_hand(room: Room, player_id: str, card: MagicCard) -> None:
    """Test/debug helper: append a canonical card to a hand."""

    room.players[player_id].magic_hand.append(card)


def unique_discard_pile(cards: Iterable[MagicCard]) -> list[MagicCard]:
    """The client-facing discard-pile view: one row per name, except 失灵！."""

    seen: set[str] = set()
    result: list[MagicCard] = []
    for card in cards:
        if card.name == "失灵！":
            result.append(card)
            continue
        if card.name in seen:
            continue
        seen.add(card.name)
        result.append(card)
    return result


def revive_sunken_ships(
    room: Room,
    owner_id: str,
    count: int = 2,
    *,
    reveal_to: str | None = None,
    selected_ships: Iterable[PlayerShip] | None = None,
) -> int:
    """Revive up to `count` sunk ships in place (疗愈, ticket #10 batch A).

    Legacy invariants:
    * dead ships normally stay in `player.ships`; a ship recorded in
      `sunken_ships` is dead even when its hits were already cleared;
    * clear `hits` and remove the registered attack on those cells from the
      **opponent's** history (otherwise that ship can never be hit again);
    * never revive a duplicate/ghost entry;
    * thaw the ship (a sunk frozen ship keeps its marker in the old stack).
    """

    player = room.players.get(owner_id)
    if player is None or count <= 0:
        return 0
    revived = 0
    guard = 0
    selected = list(selected_ships) if selected_ships is not None else None
    while revived < int(count) and player.sunken_ships and guard < 32:
        guard += 1
        if selected is not None:
            if not selected:
                break
            ship = selected.pop(0)
            if ship not in player.sunken_ships:
                continue
            player.sunken_ships.remove(ship)
        else:
            ship = player.sunken_ships.pop()
        if selected is None and ship in player.ships and is_ship_alive(player, ship):
            # A live duplicate entry: drop the ghost record, do not count it.
            continue
        while ship in player.sunken_ships:
            player.sunken_ships.remove(ship)
        if ship not in player.ships:
            player.ships.append(ship)
        ship.hits = []
        for position in ship.positions:
            position.hit = False
        ship.frozen = None
        ship.shield = False
        ship.invincible = False
        _clear_attacks_on_cells(room, owner_id, ship.positions)
        if reveal_to:
            _reveal(room, reveal_to, ship.positions, kind="heal")
        player.remaining_ships += 1
        revived += 1
    return revived


def _clear_attacks_on_cells(room: Room, owner_id: str, positions: Iterable[Position]) -> None:
    """Remove the opponent's shots at those cells (same coordinate space)."""

    cells = {(pos.x, pos.y) for pos in positions}
    if not cells:
        return
    opponent_id = next((pid for pid in room.players if pid != owner_id), None)
    if not opponent_id:
        return
    opponent = room.players[opponent_id]
    opponent.attacks = [
        attack for attack in (opponent.attacks or [])
        if (attack.x, attack.y) not in cells
    ]


def _reveal(room: Room, player_id: str, positions: Iterable[Position], *, kind: str | None = None) -> None:
    """Add cells to a player's revealed set; the service emits the frame."""

    player = room.players.get(player_id)
    if player is None:
        return
    for position in positions:
        if not any(p.x == position.x and p.y == position.y for p in player.revealed_positions):
            player.revealed_positions.append(Position(x=position.x, y=position.y))


__all__ = [
    "DrawResult",
    "draw_card",
    "draw_to_hand",
    "init_shared_deck",
    "revive_sunken_ships",
    "unique_discard_pile",
]
