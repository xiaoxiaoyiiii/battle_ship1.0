"""魔法卡数据：50 条 / 48 个唯一卡名，逐字来自旧栈 `magic_card.json`。

数据文件是 `data/magic_card.json`，SHA-256 与旧栈
`static/magic_card.json` 完全一致。卡名/速阶/类型/描述只在这里加载一次，
卡效果分发、前端同步与图鉴都读同一份对象。

「失灵！」有 3 条是**故意**的：`draw_card` 的去重规则对它特例放行
（同一手牌里可以有 3 张）。「钢筋铁骨」保留在卡表与效果表里，但
`HIDDEN_CARD_NAMES` 让它不进共享牌堆，所以谁也摸不到。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

CARD_DATA_PATH = Path(__file__).with_name("data") / "magic_card.json"
CARD_COUNT = 50
UNIQUE_CARD_COUNT = 48
HIDDEN_CARD_NAMES = frozenset({"钢筋铁骨"})
DUPLICATE_ALLOWED = frozenset({"失灵！"})


class CardDataError(ValueError):
    """The frozen card table on disk is malformed."""


@dataclass(frozen=True)
class MagicCard:
    name: str
    speed: int
    type: str
    description: str

    def to_payload(self) -> dict[str, Any]:
        """Frozen wire shape: the legacy `__dict__` dump had exactly these keys."""

        return {
            "name": self.name,
            "speed": self.speed,
            "type": self.type,
            "description": self.description,
        }

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


def load_cards(path: Path | str | None = None) -> tuple[MagicCard, ...]:
    """Load and validate the frozen card table.

    Validation is deliberately strict: a missing/extra row, a duplicate name
    outside the sealed exception, or a non-canonical field must fail at import
    time instead of silently shrinking the deck (the old stack's 50/48/3 is a
    player-visible contract).
    """

    source = Path(path) if path is not None else CARD_DATA_PATH
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CardDataError(f"无法读取魔法卡数据: {error}") from error
    if not isinstance(raw, list):
        raise CardDataError("魔法卡数据必须是 JSON 数组")

    cards: list[MagicCard] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise CardDataError("魔法卡条目必须是对象")
        try:
            card = MagicCard(
                name=str(entry["name"]),
                speed=int(entry["speed"]),
                type=str(entry["type"]),
                description=str(entry["description"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise CardDataError(f"魔法卡条目字段非法: {entry!r}") from error
        if card.speed not in (1, 2, 3):
            raise CardDataError(f"魔法卡速阶非法: {card.name}={card.speed}")
        if card.type not in ("普通", "场地", "判定"):
            raise CardDataError(f"魔法卡类型非法: {card.name}={card.type}")
        cards.append(card)

    if len(cards) != CARD_COUNT:
        raise CardDataError(f"魔法卡应有 {CARD_COUNT} 条，实际 {len(cards)} 条")
    names = {card.name for card in cards}
    if len(names) != UNIQUE_CARD_COUNT:
        raise CardDataError(
            f"魔法卡应有 {UNIQUE_CARD_COUNT} 个唯一卡名，实际 {len(names)} 个"
        )
    counts: dict[str, int] = {}
    for card in cards:
        counts[card.name] = counts.get(card.name, 0) + 1
    for name, count in counts.items():
        if count > 1 and name not in DUPLICATE_ALLOWED:
            raise CardDataError(f"魔法卡名重复且未登记特例: {name} x{count}")
    if counts.get("失灵！") != 3:
        raise CardDataError("「失灵！」必须恰好 3 条（抽牌去重特例）")
    return tuple(cards)


MAGIC_CARDS: tuple[MagicCard, ...] = load_cards()

#: One canonical instance per name (the first row wins; all duplicates are the
#: same card in the frozen data).
CARD_BY_NAME: dict[str, MagicCard] = {}
for _card in MAGIC_CARDS:
    CARD_BY_NAME.setdefault(_card.name, _card)

UNIQUE_CARD_NAMES: tuple[str, ...] = tuple(CARD_BY_NAME)
DECK_CARDS: tuple[MagicCard, ...] = tuple(
    card for card in MAGIC_CARDS if card.name not in HIDDEN_CARD_NAMES
)


def card_by_name(name: Any) -> MagicCard | None:
    """Resolve a client-sent name to the canonical card (never trust its fields)."""

    if not isinstance(name, str):
        return None
    return CARD_BY_NAME.get(name)


def card_from_payload(payload: Any) -> MagicCard:
    """Legacy `MagicCard(**data['card'])`: only the name is authoritative."""

    if not isinstance(payload, dict):
        raise CardDataError("魔法卡数据必须是对象")
    name = payload.get("name")
    card = card_by_name(name)
    if card is None:
        raise CardDataError(f"未知的魔法卡: {name!r}")
    return card


def cards_matching(cards: Iterable[MagicCard], name: str) -> list[MagicCard]:
    return [card for card in cards if card.name == name]


__all__ = [
    "CARD_BY_NAME",
    "CARD_COUNT",
    "CARD_DATA_PATH",
    "CardDataError",
    "DECK_CARDS",
    "DUPLICATE_ALLOWED",
    "HIDDEN_CARD_NAMES",
    "MAGIC_CARDS",
    "MagicCard",
    "UNIQUE_CARD_COUNT",
    "UNIQUE_CARD_NAMES",
    "card_by_name",
    "card_from_payload",
    "cards_matching",
    "load_cards",
]
