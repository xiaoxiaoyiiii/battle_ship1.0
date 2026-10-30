"""Field-card placement and teardown (ticket #11).

The field slot holds the card **instance**, so replacing/tearing a field moves
that exact object to the discard pile instead of creating a copy.
"""

from __future__ import annotations

from typing import Any

from ..room import Room
from ..room.models import field_magic_name
from .cards import MagicCard
from .interaction import clear_ship_picks_by_reason


def field_active(room: Room) -> bool:
    return room.game_effects.get("papal_edict") is True or field_magic_name(room) == "教皇旨意"


def clear_field_magic_effects(room: Room, prev_field_name: str | None = None) -> bool:
    """Remove the room-level markers a field card installed."""

    removed = False
    if room.game_effects.pop("demon_contract", None) is not None:
        clear_ship_picks_by_reason(room, "demon_contract")
        removed = True
    if room.game_effects.pop("papal_edict", None) is not None:
        removed = True
    return removed


def place_field_magic(room: Room, caster_id: str, card: MagicCard) -> MagicCard | None:
    """Put card in the field slot; a different old field goes to discard."""

    old = room.field_magic
    old_name = getattr(old, "name", None)
    room.field_magic = card
    room.field_magic_owner = caster_id
    if old is not None and old_name != card.name:
        room.magic_discard.append(old)
        clear_field_magic_effects(room, prev_field_name=old_name)
    return old


def tear_down_field_magic(room: Room, caster_id: str) -> MagicCard | None:
    field = room.field_magic
    if not field:
        return None
    room.magic_discard.append(field)
    clear_field_magic_effects(room)
    room.field_magic = None
    room.field_magic_owner = None
    return field


__all__ = [
    "clear_field_magic_effects",
    "field_active",
    "place_field_magic",
    "tear_down_field_magic",
]
