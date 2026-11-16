"""卡池状态、抽卡、碎片兑换。掷骰可注入 rng，默认 secrets.SystemRandom。"""
from __future__ import annotations

import json
import secrets
import time
from typing import Any

from ..domain import gacha as rules
from ..domain.skins import (
    CURRENCY,
    DUPLICATE_SHARDS,
    EXCHANGE_COST,
    POOL_ID,
    PRICES,
    RATES,
    RATES_DISPLAY,
    REQUEST_ID_RE,
    SHARD_PER_DRAW,
    SKINS,
    SKINS_BY_ID,
    progress_of,
    skin_catalog_item,
)
from ..repositories import Database


class SkinHttpError(Exception):
    def __init__(self, status_code: int, code: str, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field = field


class GachaService:
    def __init__(self, database: Database, rng: Any | None = None) -> None:
        self.database = database
        self.rng = rng or secrets.SystemRandom()

    def view(self, user_id: str) -> dict[str, Any]:
        with self.database.unit_of_work() as uow:
            if not user_id or not uow.users.get(user_id):
                raise SkinHttpError(401, "unauthorized", "未登录", "session")
            owned = uow.skins.owned_ids(user_id)
            return {
                "ok": True,
                "pool_id": POOL_ID,
                "currency": CURRENCY,
                "balance": uow.tide_ash.balance(user_id),
                "shards": uow.skins.shard_balance(user_id),
                "prices": dict(PRICES),
                "rates": dict(RATES),
                "rates_display": [dict(item) for item in RATES_DISPLAY],
                "duplicate_shards": DUPLICATE_SHARDS,
                "shard_per_draw": SHARD_PER_DRAW,
                "exchange_cost": dict(EXCHANGE_COST),
                "pity": None,
                "skins": [skin_catalog_item(skin, owned=skin.skin_id in owned) for skin in SKINS],
                "progress": progress_of(len(owned)),
            }

    def pull(self, user_id: str, payload: Any, *, now: int | None = None) -> dict[str, Any]:
        now = int(time.time()) if now is None else int(now)
        if not isinstance(payload, dict):
            raise SkinHttpError(400, "invalid_payload", "请提供抽卡参数", "body")
        count = payload.get("count")
        request_id = payload.get("request_id")
        if type(count) is not int or count not in (1, 10):
            raise SkinHttpError(400, "invalid_count", "只能单抽或十连", "count")
        if not isinstance(request_id, str) or not REQUEST_ID_RE.fullmatch(request_id):
            raise SkinHttpError(400, "invalid_request_id", "请提供有效的请求编号", "request_id")
        cost = PRICES["single"] if count == 1 else PRICES["ten"]
        with self.database.unit_of_work() as uow:
            if not user_id or not uow.users.get(user_id):
                raise SkinHttpError(401, "unauthorized", "未登录", "session")
            uow.tide_ash.lock(user_id, now=now)
            uow.skins.lock_shards(user_id, now=now)
            existing = uow.skins.gacha_request(user_id, request_id)
            if existing is not None:
                if int(existing.count) != count:
                    raise SkinHttpError(409, "request_id_conflict", "该请求编号已用于另一次抽卡", "request_id")
                body = json.loads(existing.response)
                body["replayed"] = True
                return body
            balance = uow.tide_ash.balance(user_id)
            if balance < cost:
                raise SkinHttpError(409, "insufficient_tide_ash", "潮汐徽记不足", "count")
            if not uow.tide_ash.apply_once(user_id, "skin_gacha", request_id, -cost, now=now):
                raise SkinHttpError(409, "insufficient_tide_ash", "潮汐徽记不足", "count")
            owned = uow.skins.owned_ids(user_id)
            results = rules.draw_many(self.rng, count, owned)
            summary = rules.summarize(results)
            for row in results:
                if row["is_new"] and row["skin_id"]:
                    if uow.skins.grant_once(user_id, row["skin_id"], "gacha", request_id, now=now):
                        skin = SKINS_BY_ID[row["skin_id"]]
                        uow.skins.set_selection(user_id, skin.card_name, skin.skin_id, now=now)
            shards_gained = int(summary["shards_gained"])
            if shards_gained and not uow.skins.apply_shards_once(
                    user_id, "skin_gacha", request_id, shards_gained, now=now):
                raise RuntimeError("抽卡碎片入账冲突，事务将回滚")
            body = {
                "ok": True,
                "request_id": request_id,
                "replayed": False,
                "count": count,
                "cost": cost,
                "currency": CURRENCY,
                "results": results,
                "summary": summary,
                "balance": uow.tide_ash.balance(user_id),
                "shards": uow.skins.shard_balance(user_id),
                "progress": progress_of(len(uow.skins.owned_ids(user_id))),
            }
            uow.skins.save_gacha_request(
                user_id, request_id, pool_id=POOL_ID, count=count, cost=cost,
                response=json.dumps(body, ensure_ascii=False, separators=(",", ":")), now=now,
            )
            return body

    def exchange(self, user_id: str, payload: Any, *, now: int | None = None) -> dict[str, Any]:
        now = int(time.time()) if now is None else int(now)
        if not isinstance(payload, dict):
            raise SkinHttpError(400, "invalid_payload", "请选择要兑换的皮肤", "body")
        skin_id = payload.get("skin_id")
        if not isinstance(skin_id, str) or skin_id not in SKINS_BY_ID:
            raise SkinHttpError(400, "unknown_skin", "未知的皮肤", "skin_id")
        skin = SKINS_BY_ID[skin_id]
        cost = EXCHANGE_COST[skin.tier]
        with self.database.unit_of_work() as uow:
            if not user_id or not uow.users.get(user_id):
                raise SkinHttpError(401, "unauthorized", "未登录", "session")
            uow.skins.lock_shards(user_id, now=now)
            owned = uow.skins.owned_ids(user_id)
            if skin_id in owned:
                raise SkinHttpError(409, "skin_already_owned", "已经拥有这件皮肤", "skin_id")
            if uow.skins.shard_balance(user_id) < cost:
                raise SkinHttpError(409, "insufficient_shards", "潮汐碎片不足", "skin_id")
            if not uow.skins.apply_shards_once(user_id, "skin_exchange", skin_id, -cost, now=now):
                raise SkinHttpError(409, "insufficient_shards", "潮汐碎片不足", "skin_id")
            if not uow.skins.grant_once(user_id, skin_id, "exchange", skin_id, now=now):
                raise SkinHttpError(409, "skin_already_owned", "已经拥有这件皮肤", "skin_id")
            uow.skins.set_selection(user_id, skin.card_name, skin_id, now=now)
            owned.add(skin_id)
            return {
                "ok": True,
                "skin": skin_catalog_item(skin, owned=True),
                "cost": cost,
                "shards": uow.skins.shard_balance(user_id),
                "balance": uow.tide_ash.balance(user_id),
                "progress": progress_of(len(owned)),
            }
