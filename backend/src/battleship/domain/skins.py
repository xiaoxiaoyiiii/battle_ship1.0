"""第一批霓虹赛博卡面皮肤：稳定 id、档位、公示常量。

卡牌身份仍是中文卡名（magic_card.json 无 key）。card_key 与前端
`frontend/src/cards/cardArt.ts` 的 CARD_ART_SLUGS 对齐，skin_id = neon-<card_key>。
接口约定见仓外 CONTRACT.md（bridge/skin-gacha-v1-20261115）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

POOL_ID = "neon-v1"
CURRENCY = "tide_ash"
PRICES = {"single": 80, "ten": 800}
RATES = {"limited": 0.01, "legendary": 0.09, "shard": 0.90}
DUPLICATE_SHARDS = 5
SHARD_PER_DRAW = 1
EXCHANGE_COST = {"legendary": 20, "limited": 60}
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
RATES_DISPLAY = (
    {"kind": "limited", "label": "限定皮肤", "percent": "1%", "note": "3 款中均匀抽取，每款 0.333…%"},
    {"kind": "legendary", "label": "传说皮肤", "percent": "9%", "note": "9 款中均匀抽取，每款 1%"},
    {"kind": "shard", "label": "潮汐碎片 ×1", "percent": "90%", "note": ""},
)
TOTAL_SKINS = 12


@dataclass(frozen=True)
class Skin:
    skin_id: str
    card_key: str
    card_name: str
    tier: str


def normalize_card_key(raw: str) -> str:
    """今后新卡 slug 规范化：小写，非 [a-z0-9] 换成 '-'，合并连续 '-'，去首尾 '-'。"""
    text = "".join(ch.lower() if ch.isalnum() and ch.isascii() else "-" for ch in raw)
    while "--" in text:
        text = text.replace("--", "-")
    return text.strip("-")


# 顺序即接口 skins 数组顺序，与 CONTRACT 第 1 节一致。
SKINS: tuple[Skin, ...] = (
    Skin("neon-shiling", "shiling", "失灵！", "limited"),
    Skin("neon-emo-qiyue", "emo-qiyue", "恶魔契约", "limited"),
    Skin("neon-juechu-fengsheng", "juechu-fengsheng", "绝处逢生", "limited"),
    Skin("neon-hongzha", "hongzha", "轰炸", "legendary"),
    Skin("neon-kanpo", "kanpo", "看破！", "legendary"),
    Skin("neon-jixian-zengyuan", "jixian-zengyuan", "极限增援", "legendary"),
    Skin("neon-shenwei", "shenwei", "神威！", "legendary"),
    Skin("neon-mingyun-shaizi", "mingyun-shaizi", "命运骰子", "legendary"),
    Skin("neon-jiabailie-zhiguang", "jiabailie-zhiguang", "加百列之光", "legendary"),
    Skin("neon-jiaohuang-zhiyi", "jiaohuang-zhiyi", "教皇旨意", "legendary"),
    Skin("neon-huoli-quankai", "huoli-quankai", "火力全开", "legendary"),
    Skin("neon-kesulu-zhiyan", "kesulu-zhiyan", "克苏鲁之眼", "legendary"),
)
SKINS_BY_ID = {skin.skin_id: skin for skin in SKINS}
SKINS_BY_CARD_NAME = {skin.card_name: skin for skin in SKINS}
SKINS_BY_TIER: dict[str, tuple[Skin, ...]] = {
    "limited": tuple(skin for skin in SKINS if skin.tier == "limited"),
    "legendary": tuple(skin for skin in SKINS if skin.tier == "legendary"),
}


def skin_catalog_item(skin: Skin, *, owned: bool) -> dict:
    return {
        "skin_id": skin.skin_id,
        "card_key": skin.card_key,
        "card_name": skin.card_name,
        "tier": skin.tier,
        "owned": owned,
    }


def progress_of(owned_count: int) -> dict:
    return {"owned": int(owned_count), "total": TOTAL_SKINS, "complete": int(owned_count) >= TOTAL_SKINS}


def public_skin_id(skin_id: object, card_name: object) -> str | None:
    """公开载荷白名单：必须是目录 id 且与该行卡名匹配；否则丢弃（省略键）。"""
    if not isinstance(skin_id, str) or not isinstance(card_name, str):
        return None
    skin = SKINS_BY_ID.get(skin_id)
    if skin is None or skin.card_name != card_name:
        return None
    return skin.skin_id


def card_name_of(item: dict) -> str | None:
    card = item.get("card")
    if isinstance(card, dict):
        name = card.get("name")
        return name if isinstance(name, str) else None
    if isinstance(card, str):
        return card
    name = item.get("card_name")
    return name if isinstance(name, str) else None
