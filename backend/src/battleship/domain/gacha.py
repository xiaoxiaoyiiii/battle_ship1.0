"""皮肤抽卡纯函数：掷骰、档内均匀、重复判定。rng 可注入以便测试。"""
from __future__ import annotations

from typing import Any, Protocol

from .skins import (
    DUPLICATE_SHARDS,
    SHARD_PER_DRAW,
    SKINS_BY_TIER,
    Skin,
)


class Rng(Protocol):
    def randrange(self, stop: int) -> int: ...


def roll_kind(rng: Rng) -> str:
    """每抽独立：0=限定 1%，1-9=传说 9%，10-99=碎片 90%。"""
    roll = rng.randrange(100)
    if roll < 1:
        return "limited"
    if roll < 10:
        return "legendary"
    return "shard"


def roll_skin(rng: Rng, kind: str) -> Skin:
    pool = SKINS_BY_TIER[kind]
    return pool[rng.randrange(len(pool))]


def _shard_result(index: int) -> dict[str, Any]:
    return {
        "index": index,
        "kind": "shard",
        "skin_id": None,
        "card_key": None,
        "card_name": None,
        "is_new": False,
        "shards_gained": SHARD_PER_DRAW,
    }


def _skin_result(index: int, kind: str, skin: Skin, is_new: bool) -> dict[str, Any]:
    return {
        "index": index,
        "kind": kind,
        "skin_id": skin.skin_id,
        "card_key": skin.card_key,
        "card_name": skin.card_name,
        "is_new": is_new,
        "shards_gained": 0 if is_new else DUPLICATE_SHARDS,
    }


def draw_one(rng: Rng, owned: set[str], index: int = 0) -> dict[str, Any]:
    """抽一次并就地更新 owned（新得立即入库，同一次十连后续按已拥有算）。"""
    kind = roll_kind(rng)
    if kind == "shard":
        return _shard_result(index)
    skin = roll_skin(rng, kind)
    is_new = skin.skin_id not in owned
    if is_new:
        owned.add(skin.skin_id)
    return _skin_result(index, kind, skin, is_new)


def draw_many(rng: Rng, count: int, owned: set[str]) -> list[dict[str, Any]]:
    current = set(owned)
    return [draw_one(rng, current, index) for index in range(count)]


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "new_skins": [row["skin_id"] for row in results if row["is_new"]],
        "duplicates": sum(1 for row in results if row["kind"] != "shard" and not row["is_new"]),
        "shards_gained": sum(int(row["shards_gained"]) for row in results),
    }
