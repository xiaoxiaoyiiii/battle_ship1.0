"""The single card-name -> effect dispatch table (ticket #10).

There is exactly one registry. A card name is either registered here or it is
not playable yet: the service refuses it **before** removing the card from the
hand, so an unimplemented batch can never silently eat a card (the legacy stack
deducted first and refunded only after a failed effect).
"""

from __future__ import annotations

from typing import Awaitable, Callable

from .cards import MagicCard
from .effects.base import EffectContext, EffectResult

EffectFn = Callable[[EffectContext], Awaitable[EffectResult]]

_EFFECTS: dict[str, EffectFn] = {}


def register(name: str) -> Callable[[EffectFn], EffectFn]:
    """Register the one effect implementation for a canonical card name."""

    def decorator(function: EffectFn) -> EffectFn:
        if name in _EFFECTS:
            raise RuntimeError(f"魔法卡效果重复登记: {name}")
        _EFFECTS[name] = function
        return function

    return decorator


def effect_for(card: MagicCard | str) -> EffectFn | None:
    name = card if isinstance(card, str) else card.name
    return _EFFECTS.get(name)


def is_implemented(card: MagicCard | str) -> bool:
    return effect_for(card) is not None


def implemented_cards() -> tuple[str, ...]:
    return tuple(_EFFECTS)


# Importing the batch modules is what performs the registration. Keep this at
# the bottom so the decorator exists before the modules import it.
from .effects import batch_a as _batch_a  # noqa: E402,F401
from .effects import batch_b as _batch_b  # noqa: E402,F401
from .effects import chain_cards as _chain_cards  # noqa: E402,F401

__all__ = [
    "EffectFn",
    "effect_for",
    "implemented_cards",
    "is_implemented",
    "register",
]