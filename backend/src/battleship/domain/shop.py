"""首版常驻外观目录，复用资料页的真实解锁判据。"""
from dataclasses import dataclass
from typing import Any

from .progression import profile_spec


@dataclass(frozen=True)
class ShopItem:
    id: str
    kind: str
    name: str
    price: int


SHOP_ITEMS = (
    ShopItem("ember_wake", "frame", "余烬尾流", 400),
    ShopItem("tideglass", "frame", "潮汐琉璃", 400),
    ShopItem("abyssal_glow", "frame", "深渊辉光", 450),
    ShopItem("coral_dawn", "card_bg", "珊瑚晨曦", 350),
    ShopItem("moonlit", "card_bg", "月照海面", 350),
    ShopItem("kelp_green", "card_bg", "海藻青", 300),
    ShopItem("stardust", "pointer_effect", "星尘航迹", 450),
    ShopItem("pulse", "title_effect", "潮汐呼吸", 450),
    ShopItem("aurora_drift", "profile_bg", "极光漂流", 500),
    ShopItem("nebula_wake", "profile_bg", "星云尾迹", 550),
)
SHOP_BY_ID = {item.id: item for item in SHOP_ITEMS}

# 对外沿用槽位名，权益沿用资料系统已经消费的键。
STORAGE_KINDS = {"pointer_effect": "pointer", "title_effect": "title_fx"}


def storage_kind(kind: str) -> str:
    return STORAGE_KINDS.get(kind, kind)


def owned_cosmetics(stats: dict[str, Any]) -> set[tuple[str, str]]:
    checks = {
        "title": profile_spec.unlocked_titles,
        "frame": profile_spec.unlocked_frames,
        "card_bg": profile_spec.unlocked_card_bgs,
        "profile_bg": profile_spec.unlocked_profile_bgs,
        "pointer": profile_spec.unlocked_pointer_effects,
        "title_fx": profile_spec.unlocked_title_effects,
    }
    return {(kind, reward_id) for kind, check in checks.items() for reward_id in check(stats)}
