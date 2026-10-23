"""Effect lifetimes (ticket #11/#38): board cleanup only.

Per-player EffectFlags no longer have a whitelist here: every persistent flag is
a lease on the effect bus (ticket #36) and expires at its own turn/round/match
boundary. This module keeps only the board-scoped cleanup vocabulary, which is
about room.game_effects rather than flags.
"""

from __future__ import annotations

from ..room import Room

#: key -> human text. The legacy stack emitted three helper-only event names
#: (holy_heart_cleared / reinforcement_cleared / demon_contract_cleared) that are
#: not in the frozen 82-literal outbound table; ticket #11 keeps the contract
#: exact and tells the client through game_message + active_effects instead.
_MULTITURN_EFFECTS: tuple[tuple[str, str], ...] = (
    ("holy_heart", "无暇圣心效果已终止"),
    ("reinforcement_check", "极限增援效果已终止"),
)
_MULTITURN_PREFIXES: tuple[str, ...] = ("prediction", "prediction_initial_")


def clear_board_effects(room: Room, player_ids: list[str], why: str = "") -> list[tuple[str, dict]]:
    """Terminate board-scoped effects on the boards that were just replaced.

    Returns the wire frames the caller must emit (this module never emits).
    """

    ids = [str(pid) for pid in player_ids or []]
    if not ids:
        return []
    effects = room.game_effects if isinstance(room.game_effects, dict) else {}
    frames: list[tuple[str, dict]] = []

    # Excluded (神威!) ships belong to the replaced board; restore-at-expiry
    # would otherwise append ghost ships (6 -> 8 ships in the legacy bug).
    entries = effects.get("excluded_ships")
    if entries:
        if len(ids) >= len(room.players):
            effects.pop("excluded_ships", None)
        else:
            kept = [e for e in entries if e.get("player") not in ids]
            if kept:
                effects["excluded_ships"] = kept
            else:
                effects.pop("excluded_ships", None)

    holes = effects.get("shenwei_holes") or []
    for pid in ids:
        mine = [h for h in holes if isinstance(h, dict) and str(h.get("player")) == pid]
        if not mine:
            continue
        for hole in mine:
            holes.remove(hole)
        frames.append(("shenwei_hole_restored", {"player": pid}))
    if not holes:
        effects.pop("shenwei_holes", None)

    area = effects.get("frozen_area")
    if isinstance(area, dict) and str(area.get("owner")) in ids:
        effects.pop("frozen_area", None)
        frames.append(("frozen_area", {"cleared": True}))
    return frames


def clear_multiturn_effects(room: Room, why: str = "") -> list[tuple[str, dict]]:
    """Terminate cross-round countdown effects when a board is replaced."""

    effects = room.game_effects if isinstance(room.game_effects, dict) else {}
    frames: list[tuple[str, dict]] = []
    for key, text in _MULTITURN_EFFECTS:
        if key not in effects:
            continue
        effects.pop(key, None)
        frames.append(("game_message", {"message": text, "type": "info", "reason": why}))
        if key == "demon_contract":
            from .interaction import clear_ship_picks_by_reason

            clear_ship_picks_by_reason(room, "demon_contract")
    for key in list(effects):
        if any(str(key).startswith(prefix) for prefix in _MULTITURN_PREFIXES):
            effects.pop(key, None)
    return frames


__all__ = [
    "clear_board_effects",
    "clear_multiturn_effects",
]
