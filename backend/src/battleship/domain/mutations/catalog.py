"""每周目录、周历与抽选；目录只从同一份配置读取。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
import json
from pathlib import Path
import random
from typing import Any

DATA = Path(__file__).with_name("data")
BEIJING = timezone(timedelta(hours=8))


@lru_cache(maxsize=1)
def _configuration() -> tuple[dict[str, dict], dict, set[frozenset[str]]]:
    catalog = json.loads((DATA / "catalog.json").read_text(encoding="utf-8"))
    calendar = json.loads((DATA / "calendar.json").read_text(encoding="utf-8"))
    entries = catalog["entries"]
    by_id = {entry["id"]: entry for entry in entries}
    if len(by_id) != len(entries) or len(entries) != 14 or {"A2", "D3"} & by_id.keys():
        raise ValueError("突变目录存在重复、缺失或已删除词条")
    for entry in entries:
        if entry["group"] not in {"ATK", "SPEED", "HAND", "TEMPO", "FOG"} or not entry["description"]:
            raise ValueError("突变词条缺少互斥组或完整文案")
    blacklist = {frozenset(pair) for pair in catalog["pair_blacklist"]}
    packs = {pack["id"]: pack for pack in calendar["packs"]}
    for pack in packs.values():
        if not 4 <= len(pack["entries"]) <= 6 or len(set(pack["entries"])) != len(pack["entries"]):
            raise ValueError("周包必须包含4至6条不同词条")
        if any(key not in by_id for key in pack["entries"]):
            raise ValueError("周包引用了未知词条")
    if not calendar["rotation"] or any(key not in packs for key in calendar["rotation"]):
        raise ValueError("周历引用了未知周包")
    return by_id, calendar, blacklist


def entries_for(ids: list[str]) -> list[dict]:
    by_id, _, _ = _configuration()
    return [dict(by_id[key]) for key in ids]


def validate_selection(ids: Any) -> str | None:
    if not isinstance(ids, list) or any(not isinstance(key, str) for key in ids):
        return "请选择有效的突变词条列表"
    by_id, _, blacklist = _configuration()
    if len(set(ids)) != len(ids) or any(key not in by_id for key in ids):
        return "突变词条重复或不存在"
    groups: set[str] = set()
    for index, key in enumerate(ids):
        group = by_id[key]["group"]
        if group in groups:
            return "同一互斥组不能同时选择"
        groups.add(group)
        if any(frozenset((key, other)) in blacklist for other in ids[:index]):
            return "这组突变不能同时生效"
    return None


def roll_mutations(pack: list[str], rng: Any = random) -> list[str]:
    by_id, _, _ = _configuration()
    if not pack or len(set(pack)) != len(pack) or any(key not in by_id for key in pack):
        raise ValueError("无效的突变抽选池")
    count = 2 if rng.random() < .25 and len(pack) > 1 else 1
    picked = list(rng.sample(pack, count))
    return picked[:1] if validate_selection(picked) else picked


def weekly_pack(now: datetime | float | None = None) -> dict:
    by_id, calendar, blacklist = _configuration()
    if isinstance(now, (int, float)):
        now = datetime.fromtimestamp(now, BEIJING)
    elif now is None:
        now = datetime.now(BEIJING)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=BEIJING)
    local = now.astimezone(BEIJING)
    year, week, _ = local.isocalendar()
    week_id = f"{year}-W{week:02d}"
    anchor_year, anchor_week = calendar["anchor_week"].split("-W")
    anchor = datetime.fromisocalendar(int(anchor_year), int(anchor_week), 1).date()
    monday = local.date() - timedelta(days=local.weekday())
    rotation = calendar["rotation"]
    pack_id = calendar["weeks"].get(week_id) or rotation[((monday - anchor).days // 7) % len(rotation)]
    pack = next(pack for pack in calendar["packs"] if pack["id"] == pack_id)
    return {
        "week_id": week_id, "pack_id": pack_id, "name": pack["name"],
        "entries": entries_for(pack["entries"]),
        "catalog": [dict(entry) for entry in by_id.values()],
        "pair_blacklist": [sorted(pair) for pair in sorted(blacklist, key=lambda pair: sorted(pair))],
    }
