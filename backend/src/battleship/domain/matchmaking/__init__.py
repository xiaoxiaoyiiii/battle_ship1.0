"""Matchmaking domain rules (ticket #16).

Only pairing preference lives here; the queue itself belongs to the service.
"""

from .guard import (  # noqa: F401
    Candidate,
    RECENT_OPPONENT_COOLDOWN_SEC,
    RECENT_OPPONENT_LOOKBACK,
    hard_block,
    pair_score,
    pick_pair,
    usable_ip,
)

__all__ = [
    "Candidate",
    "RECENT_OPPONENT_COOLDOWN_SEC",
    "RECENT_OPPONENT_LOOKBACK",
    "hard_block",
    "pair_score",
    "pick_pair",
    "usable_ip",
]
