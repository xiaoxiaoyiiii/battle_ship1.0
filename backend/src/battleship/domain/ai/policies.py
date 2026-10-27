"""easy / normal / hard AI policies (the master tier lives in master.py).

One implementation, shared by every caller: the AI turn driver, the chain
response window and the out-of-repo self-play harness all read these functions,
so a measurement never runs against a copy of the policy.

Difficulty is resolved **per seat** (difficulty.py, lesson #35):

* easy   -- fires only, never plays a card;
* normal -- at most one card per turn, from the safe list below;
* hard   -- normal + 使用合法反制牌响应连锁；
* master -- the decision layer in master.py (pool, 3 cards, interleaved play,
            fires on recon)，并共用困难档的连锁反制。

The card policy is the frozen legacy one: pick the cheapest-speed card from the
safe list. That list exists because cards that wait for the **caster's own**
click/placement have no consumer for easy/normal/hard; playing one would freeze
the room on that turn (lesson #38).
"""

from __future__ import annotations

import random
from typing import Any

from .. import battle as battle_rules
from ..magic import chain as chain_rules
from ..magic.rules import can_play_magic_card
from . import master
from .difficulty import difficulty_of, is_master

#: Cards easy/normal/hard may play: no target, no follow-up choice, no
#: "must have just hit / just sunk" precondition. Everything else stays out.
#:   (1) 桃园结义 / 明智埋葬 / 神机妙算 / 仁王之盾 / 灵气复苏 / 增援 / 死者苏生 /
#:       绝处逢生 / 回光返照 / 败者食尘 wait for the caster's own click or
#:       placement; easy/normal/hard have no consumer, so playing one freezes
#:       the turn;
#:   (2) 溅射 / 雷达子弹 / 饮血 / 越战越勇 need a hit/sink right before them,
#:       and a blind play is only refunded.
#: Widening this list requires cases/13-ai's "no pending left behind" test.
AI_SAFE_CARDS: tuple[str, ...] = (
    "余音绕梁",
    "火力全开",
    "无中生有",
    "极限增援",
    "无暇圣心",
    "看破！",
    "五险一金",
    "八方来财",
    "百亿补贴",
)


def _rng(rng: Any | None = None) -> Any:
    """Caller RNG, else the module-level random (never random.Random(), #36)."""

    return rng if rng is not None else random


def cards_per_turn(room: Any, player_id: str | None) -> int:
    """Play budget for this seat: 0 easy, 1 normal/hard, CARDS_PER_TURN master."""

    difficulty = difficulty_of(room, player_id)
    if difficulty == "easy":
        return 0
    if difficulty == "master":
        return int(master.CARDS_PER_TURN)
    return 1


def choose_safe_card_index(room: Any, player_id: str) -> int | None:
    """normal/hard: the lowest-speed safe card that is playable right now.

    Pure decision (no state change), so it can be asserted directly. Returns the
    hand index or None. easy never reaches this (budget 0) and master uses
    master.choose_card; both are guarded here as well.
    """

    difficulty = difficulty_of(room, player_id)
    if difficulty not in ("normal", "hard"):
        return None
    player = (getattr(room, "players", None) or {}).get(player_id)
    if player is None or not player.magic_hand:
        return None
    candidates: list[tuple[int, int]] = []
    for index, card in enumerate(player.magic_hand):
        if getattr(card, "name", None) not in AI_SAFE_CARDS:
            continue
        if not can_play_magic_card(room, player_id, card):
            continue
        candidates.append((int(getattr(card, "speed", 0) or 0), index))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def choose_attack(room: Any, player_id: str,
                  rng: Any | None = None) -> tuple[int, int] | None:
    """This seat's next shot; None when there is no legal cell.

    Single entry for both the AI turn driver and the self-play harness. Master
    reads its recon first (guaranteed hits), the other tiers fire uniformly at
    random among cells they have not used yet -- exactly the legacy policy.
    """

    player = (getattr(room, "players", None) or {}).get(player_id)
    if player is None:
        return None
    cells = battle_rules.attackable_cells(player)
    if not cells:
        return None
    if is_master(room, player_id):
        shot = master.choose_attack(room, player_id, rng=rng)
        if shot is not None:
            return shot
    return _rng(rng).choice(cells)


def choose_chain_response(room: Any, player_id: str) -> dict[str, Any] | None:
    """困难和大师使用与开窗资格相同的选牌结果；没有合法反制时让过。"""

    card = chain_rules.choose_ai_response_card(room, player_id)
    if card is None:
        return None
    return {"chain": True, "card": {"name": card.name, "speed": card.speed,
                                    "type": card.type}, "targets": []}


def resolve_ship_pick(room: Any, player_id: str, reason: Any,
                      candidates: Any, rng: Any | None = None) -> Any | None:
    """Pick one of the seat's own living ships (synchronous AI answer).

    Master uses its own valuation; the other tiers keep the legacy uniform
    random choice. Must never return None while candidates exist: returning None
    would leave the seat's ship-pick pending unconsumed and freeze the turn.
    """

    cands = [ship for ship in (candidates or []) if ship is not None]
    if not cands:
        return None
    if is_master(room, player_id):
        picked = master.resolve_ship_pick(room, player_id, reason, cands, rng=rng)
        if picked is not None:
            return picked
    return _rng(rng).choice(cands)


def resolve_placement(room: Any, player_id: str, kind: Any,
                      candidates: Any, rng: Any | None = None) -> Any | None:
    """Pick a legal cell for a new ship (candidates are pre-filtered)."""

    cands = [cell for cell in (candidates or []) if cell is not None]
    if not cands:
        return None
    if is_master(room, player_id):
        picked = master.resolve_placement(room, player_id, kind, cands, rng=rng)
        if picked is not None:
            return picked
    return _rng(rng).choice(cands)


def resolve_choice(room: Any, player_id: str, kind: Any, options: Any,
                   rng: Any | None = None) -> Any | None:
    """Pick one option for a card prompt (master values it; others take the first)."""

    opts = list(options or [])
    if not opts:
        return None
    if is_master(room, player_id):
        picked = master.resolve_choice(room, player_id, kind, opts, rng=rng)
        if picked is not None:
            return picked
    return opts[0]


def owns_interaction(card_name: str) -> bool:
    """Whether the AI turn has an in-place consumer for this card's pending.

    Used by the pool-coverage test: a card whose pending channel the driver
    cannot answer must never be playable by any AI tier.
    """

    channels = master.CARD_PENDING_CHANNELS.get(str(card_name or ""), ())
    return all(channel in master.AI_CONSUMED_CHANNELS for channel in channels)


__all__ = [
    "AI_SAFE_CARDS",
    "cards_per_turn",
    "choose_attack",
    "choose_chain_response",
    "choose_safe_card_index",
    "difficulty_of",
    "is_master",
    "owns_interaction",
    "resolve_choice",
    "resolve_placement",
    "resolve_ship_pick",
]
