"""旧 GameRoom 与纯连锁状态之间的只读适配器。"""
from __future__ import annotations

from typing import Any

from domain.chain import ChainItemState, ChainState


def build_chain_state(room: Any) -> ChainState:
    items = []
    for index, item in enumerate(getattr(room, "chain", None) or []):
        card = getattr(item, "card", None)
        card_name = getattr(card, "name", card if isinstance(card, str) else
                           getattr(item, "card_name", ""))
        items.append(ChainItemState(
            item_id=str(getattr(item, "item_id", index)),
            caster_id=str(getattr(item, "player_id", "")),
            card_name=str(card_name),
            targets=getattr(item, "targets", None),
            timestamp=float(getattr(item, "timestamp", 0.0)),
            negated=bool(getattr(item, "negated", False)),
            negated_by=getattr(item, "negated_by", None),
        ))
    return ChainState(tuple(items), getattr(room, "chain_window", None),
                      int(getattr(room, "chain_passes", 0)),
                      bool(getattr(room, "chain_waiting", False)))
