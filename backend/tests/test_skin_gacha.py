"""卡面皮肤抽卡 v1：接口、规则、选用与公开载荷。掷骰全部脚本化，不摸运气。"""
from __future__ import annotations

import os
from pathlib import Path

_BOOT = Path("/tmp/skin-gacha-boot")
if os.name == "nt":
    _BOOT = Path(os.environ.get("TEMP", ".") ) / "skin-gacha-boot"
_BOOT.mkdir(parents=True, exist_ok=True)
(_BOOT / "dist").mkdir(exist_ok=True)
(_BOOT / "dist" / "index.html").write_text("<!doctype html><html></html>", encoding="utf-8")
os.environ["SECRET_KEY"] = "test-secret-skin-gacha-v1"
os.environ["BATTLESHIP_DB_PATH"] = str(_BOOT / "boot.db")
os.environ["FRONTEND_DIST"] = str(_BOOT / "dist")
os.environ["FRONTEND_MODE"] = "spa"
os.environ["LOG_LEVEL"] = "ERROR"
os.environ["LOG_JSON"] = "false"
os.environ["DEBUG_ADMIN_USER_IDS"] = ""

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from battleship.config import Settings
from battleship.domain.gacha import draw_many, roll_kind, roll_skin, summarize
from battleship.domain.magic.cards import CARD_BY_NAME
from battleship.domain.magic.chain import ChainItem, ChainResult
from battleship.domain.replay import _chain_items
from battleship.domain.room.sync import card_payload
from battleship.domain.skins import SKINS, SKINS_BY_CARD_NAME, SKINS_BY_ID, public_skin_id
from battleship.domain.spectate.rules import PREVIEW_KEYS, sanitize_preview_item
from battleship.domain.viewing import public_cue
from battleship.main import create_application
from battleship.repositories.migrations import migrate_database
from battleship.services.shop import ShopService

REPO_ROOT = Path(__file__).resolve().parents[2]
PUZZLES = REPO_ROOT / "config" / "daily_puzzles.json"
LIMITED = [skin for skin in SKINS if skin.tier == "limited"]
LEGENDARY = [skin for skin in SKINS if skin.tier == "legendary"]


class ScriptedRng:
    def __init__(self, values: list[int]) -> None:
        self.values = list(values)

    def randrange(self, stop: int) -> int:
        if not self.values:
            raise AssertionError(f"rng 已耗尽，还需要 <{stop}")
        value = self.values.pop(0)
        assert 0 <= value < stop, (value, stop)
        return value


@pytest.fixture
def stack(tmp_path):
    database = tmp_path / "skin-gacha.db"
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><html></html>", encoding="utf-8")
    migrate_database(database, backup=False, verify=True)
    settings = Settings(
        _env_file=None,
        secret_key=SecretStr("test-secret-skin-gacha-v1"),
        database_path=database,
        frontend_dist=dist,
        daily_puzzles_path=PUZZLES,
        log_json=False,
        log_level="ERROR",
    )
    created = create_application(settings)
    app = created.fastapi
    with TestClient(app) as client:
        yield app, client


def register(client: TestClient, name: str) -> dict:
    response = client.post("/register", json={"username": name, "password": "secret1"})
    assert response.status_code == 200, response.text
    return response.json()["user"]


def grant_tide(app, user_id: str, amount: int, source_id: str) -> None:
    with app.state.database.unit_of_work() as uow:
        assert uow.tide_ash.apply_once(user_id, "test_grant", source_id, amount)


def grant_shards(app, user_id: str, amount: int, source_id: str) -> None:
    with app.state.database.unit_of_work() as uow:
        assert uow.skins.apply_shards_once(user_id, "test_grant", source_id, amount, now=1)


def grant_skins(app, user_id: str, skin_ids: list[str], source_id: str = "seed") -> None:
    with app.state.database.unit_of_work() as uow:
        for skin_id in skin_ids:
            assert uow.skins.grant_once(user_id, skin_id, "gacha", source_id, now=1)


def error_of(response):
    payload = response.json()
    assert "error" in payload, payload
    return payload["error"]


def legendary_draw(skin_index: int) -> list[int]:
    return [1, skin_index]


def limited_draw(skin_index: int) -> list[int]:
    return [0, skin_index]


def shard_draw() -> list[int]:
    return [10]


# --------------------------------------------------------------------------- domain


def test_catalog_matches_card_table_and_slugs():
    assert len(SKINS) == 12
    assert len(LIMITED) == 3 and len(LEGENDARY) == 9
    assert [skin.card_name for skin in LIMITED] == ["失灵！", "恶魔契约", "绝处逢生"]
    for skin in SKINS:
        assert skin.card_name in CARD_BY_NAME
        assert skin.skin_id == "neon-" + skin.card_key
        assert skin is SKINS_BY_ID[skin.skin_id]
        assert SKINS_BY_CARD_NAME[skin.card_name] is skin


def test_roll_kind_and_tier_uniform_are_deterministic():
    assert roll_kind(ScriptedRng([0])) == "limited"
    assert roll_kind(ScriptedRng([1])) == "legendary"
    assert roll_kind(ScriptedRng([9])) == "legendary"
    assert roll_kind(ScriptedRng([10])) == "shard"
    assert roll_kind(ScriptedRng([99])) == "shard"
    assert roll_skin(ScriptedRng([0]), "limited").skin_id == "neon-shiling"
    assert roll_skin(ScriptedRng([1]), "limited").skin_id == "neon-emo-qiyue"
    assert roll_skin(ScriptedRng([2]), "limited").skin_id == "neon-juechu-fengsheng"
    assert roll_skin(ScriptedRng([1]), "legendary").skin_id == "neon-kanpo"


def test_draw_duplicate_within_ten_and_complete_set():
    owned: set[str] = set()
    results = draw_many(ScriptedRng(legendary_draw(0) + legendary_draw(0) + shard_draw()), 3, owned)
    assert results[0]["is_new"] is True and results[0]["shards_gained"] == 0
    assert results[1]["skin_id"] == results[0]["skin_id"]
    assert results[1]["is_new"] is False and results[1]["shards_gained"] == 5
    assert results[2]["kind"] == "shard" and results[2]["shards_gained"] == 1
    assert summarize(results) == {
        "new_skins": ["neon-hongzha"],
        "duplicates": 1,
        "shards_gained": 6,
    }
    complete = {skin.skin_id for skin in SKINS}
    again = draw_many(ScriptedRng(limited_draw(0)), 1, complete)
    assert again[0]["is_new"] is False and again[0]["shards_gained"] == 5


# --------------------------------------------------------------------------- http auth / pool / shop


def test_gacha_requires_login(stack):
    app, client = stack
    for method, path in (
        ("GET", "/api/shop/gacha"),
        ("POST", "/api/shop/gacha/pull"),
        ("POST", "/api/shop/gacha/exchange"),
        ("PUT", "/api/collection/skin"),
        ("GET", "/api/collection"),
    ):
        response = client.request(method, path, json={})
        assert response.status_code == 401, (path, response.text)
        error = error_of(response)
        assert error["code"] == "unauthorized"
        assert error["field"] == "session"


def test_pool_status_and_shop_excludes_skins(stack):
    app, client = stack
    user = register(client, "pool_user")
    grant_tide(app, user["id"], 200, "seed")
    body = client.get("/api/shop/gacha").json()
    assert body["ok"] is True
    assert body["currency"] == "tide_ash"
    assert body["balance"] == 200
    assert body["shards"] == 0
    assert body["prices"] == {"single": 80, "ten": 800}
    assert body["rates"] == {"limited": 0.01, "legendary": 0.09, "shard": 0.90}
    assert body["pity"] is None
    assert body["exchange_cost"] == {"legendary": 20, "limited": 60}
    assert body["progress"] == {"owned": 0, "total": 12, "complete": False}
    assert [row["skin_id"] for row in body["skins"]] == [skin.skin_id for skin in SKINS]
    assert all(row["owned"] is False for row in body["skins"])
    shop = client.get("/api/shop").json()
    assert shop["ok"] is True
    assert all(not str(item["id"]).startswith("neon-") for item in shop["items"])
    denied = client.post("/api/shop/purchase", json={"item_id": "neon-shiling"})
    assert denied.status_code == 400
    assert denied.json() == {"ok": False, "reason": "item_unavailable"}
    service = ShopService(app.state.database)
    catalog = [item["id"] for item in service.view(user["id"])["items"]]
    assert all(not item.startswith("neon-") for item in catalog)


def test_insufficient_tide_ash_does_not_charge(stack):
    app, client = stack
    user = register(client, "poor_user")
    grant_tide(app, user["id"], 79, "seed")
    response = client.post("/api/shop/gacha/pull", json={"count": 1, "request_id": "req-poor-1"})
    assert response.status_code == 409
    assert error_of(response)["code"] == "insufficient_tide_ash"
    assert client.get("/api/shop/gacha").json()["balance"] == 79
    grant_tide(app, user["id"], 720, "seed2")
    assert client.get("/api/shop/gacha").json()["balance"] == 799
    response = client.post("/api/shop/gacha/pull", json={"count": 10, "request_id": "req-poor-10"})
    assert response.status_code == 409
    assert error_of(response)["code"] == "insufficient_tide_ash"
    assert client.get("/api/shop/gacha").json()["balance"] == 799


def test_invalid_pull_payload(stack):
    app, client = stack
    register(client, "bad_payload")
    bad_count = client.post("/api/shop/gacha/pull", json={"count": 2, "request_id": "req-xxxx"})
    assert bad_count.status_code == 400 and error_of(bad_count)["code"] == "invalid_count"
    as_bool = client.post("/api/shop/gacha/pull", json={"count": True, "request_id": "req-xxxx"})
    assert as_bool.status_code == 400 and error_of(as_bool)["code"] == "invalid_count"
    bad_id = client.post("/api/shop/gacha/pull", json={"count": 1, "request_id": "short"})
    assert bad_id.status_code == 400 and error_of(bad_id)["code"] == "invalid_request_id"


def test_single_and_ten_pull_charge_idempotent(stack):
    app, client = stack
    user = register(client, "pull_user")
    grant_tide(app, user["id"], 1000, "seed")
    app.state.gacha.rng = ScriptedRng(legendary_draw(1))
    first = client.post("/api/shop/gacha/pull", json={"count": 1, "request_id": "pull-single-01"})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["replayed"] is False
    assert body["cost"] == 80 and body["count"] == 1 and len(body["results"]) == 1
    assert body["results"][0] == {
        "index": 0, "kind": "legendary", "skin_id": "neon-kanpo", "card_key": "kanpo",
        "card_name": "看破！", "is_new": True, "shards_gained": 0,
    }
    assert body["balance"] == 920 and body["shards"] == 0
    assert body["progress"]["owned"] == 1
    app.state.gacha.rng = ScriptedRng([])  # 若重放仍掷骰会立刻失败
    replay = client.post("/api/shop/gacha/pull", json={"count": 1, "request_id": "pull-single-01"})
    assert replay.status_code == 200
    replayed = replay.json()
    assert replayed["replayed"] is True
    assert replayed["results"] == body["results"]
    assert replayed["balance"] == 920 and replayed["shards"] == 0
    assert client.get("/api/shop/gacha").json()["balance"] == 920
    conflict = client.post("/api/shop/gacha/pull", json={"count": 10, "request_id": "pull-single-01"})
    assert conflict.status_code == 409
    assert error_of(conflict)["code"] == "request_id_conflict"

    app.state.gacha.rng = ScriptedRng(
        shard_draw() + legendary_draw(1) + legendary_draw(0) + limited_draw(1) + shard_draw() * 6
    )
    ten = client.post("/api/shop/gacha/pull", json={"count": 10, "request_id": "pull-ten-00001"})
    assert ten.status_code == 200, ten.text
    ten_body = ten.json()
    assert ten_body["cost"] == 800 and len(ten_body["results"]) == 10
    assert ten_body["results"][0]["kind"] == "shard" and ten_body["results"][0]["shards_gained"] == 1
    assert ten_body["results"][1]["skin_id"] == "neon-kanpo"
    assert ten_body["results"][1]["is_new"] is False and ten_body["results"][1]["shards_gained"] == 5
    assert ten_body["results"][2]["skin_id"] == "neon-hongzha" and ten_body["results"][2]["is_new"] is True
    assert ten_body["results"][3]["skin_id"] == "neon-emo-qiyue" and ten_body["results"][3]["is_new"] is True
    assert ten_body["summary"]["shards_gained"] == 12
    assert ten_body["balance"] == 120
    assert ten_body["shards"] == 12
    assert ten_body["progress"]["owned"] == 3
    with app.state.database.unit_of_work() as uow:
        from sqlalchemy import select
        from battleship.repositories.models import TideAshLedger
        ledgers = list(uow.session.scalars(select(TideAshLedger).where(
            TideAshLedger.user_id == user["id"], TideAshLedger.source_kind == "skin_gacha")))
        assert {(row.source_id, row.delta) for row in ledgers} == {("pull-single-01", -80), ("pull-ten-00001", -800)}


def test_complete_set_still_returns_duplicate_shards(stack):
    app, client = stack
    user = register(client, "complete_user")
    grant_tide(app, user["id"], 80, "seed")
    grant_skins(app, user["id"], [skin.skin_id for skin in SKINS])
    app.state.gacha.rng = ScriptedRng(limited_draw(2))
    body = client.post("/api/shop/gacha/pull", json={"count": 1, "request_id": "pull-complete1"}).json()
    assert body["results"][0]["is_new"] is False
    assert body["results"][0]["shards_gained"] == 5
    assert body["progress"] == {"owned": 12, "total": 12, "complete": True}
    assert body["shards"] == 5
    assert client.get("/api/shop/gacha").json()["progress"]["complete"] is True


def test_exchange_success_and_errors(stack):
    app, client = stack
    user = register(client, "exchange_user")
    short = client.post("/api/shop/gacha/exchange", json={"skin_id": "neon-hongzha"})
    assert short.status_code == 409 and error_of(short)["code"] == "insufficient_shards"
    unknown = client.post("/api/shop/gacha/exchange", json={"skin_id": "neon-missing"})
    assert unknown.status_code == 400 and error_of(unknown)["code"] == "unknown_skin"
    grant_shards(app, user["id"], 60, "seed")
    ok = client.post("/api/shop/gacha/exchange", json={"skin_id": "neon-shiling"})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["ok"] is True
    assert body["skin"]["owned"] is True and body["skin"]["tier"] == "limited"
    assert body["cost"] == 60 and body["shards"] == 0
    assert body["progress"]["owned"] == 1
    again = client.post("/api/shop/gacha/exchange", json={"skin_id": "neon-shiling"})
    assert again.status_code == 409 and error_of(again)["code"] == "skin_already_owned"
    assert client.get("/api/shop/gacha").json()["shards"] == 0


def test_collection_fields_and_selection(stack):
    app, client = stack
    user = register(client, "select_user")
    collection = client.get("/api/collection").json()
    assert collection["shards"] == 0
    by_name = {card["name"]: card for card in collection["cards"]}
    shiling = by_name["失灵！"]
    assert shiling["skins"] == [{
        "skin_id": "neon-shiling", "card_key": "shiling", "tier": "limited", "owned": False,
    }]
    assert shiling["owned_skins"] == [] and shiling["selected_skin"] == "default"
    assert shiling["lit"] is False
    splash = by_name["溅射"]
    assert splash["skins"] == [] and splash["owned_skins"] == [] and splash["selected_skin"] == "default"
    denied = client.put("/api/collection/skin", json={"card_name": "失灵！", "skin": "neon-shiling"})
    assert denied.status_code == 409 and error_of(denied)["code"] == "skin_not_owned"
    mismatch = client.put("/api/collection/skin", json={"card_name": "失灵！", "skin": "neon-kanpo"})
    assert mismatch.status_code == 400 and error_of(mismatch)["code"] == "skin_card_mismatch"
    unknown = client.put("/api/collection/skin", json={"card_name": "不存在", "skin": "default"})
    assert unknown.status_code == 400 and error_of(unknown)["code"] == "unknown_card"
    grant_skins(app, user["id"], ["neon-shiling"])
    # 未点亮也可选用
    selected = client.put("/api/collection/skin", json={"card_name": "失灵！", "skin": "neon-shiling"})
    assert selected.status_code == 200, selected.text
    assert selected.json() == {"ok": True, "card_name": "失灵！", "selected_skin": "neon-shiling"}
    after = {card["name"]: card for card in client.get("/api/collection").json()["cards"]}["失灵！"]
    assert after["owned_skins"] == ["neon-shiling"]
    assert after["selected_skin"] == "neon-shiling"
    assert after["skins"][0]["owned"] is True
    assert after["lit"] is False
    reset = client.put("/api/collection/skin", json={"card_name": "失灵！", "skin": "default"})
    assert reset.json()["selected_skin"] == "default"
    assert {card["name"]: card for card in client.get("/api/collection").json()["cards"]}["失灵！"]["selected_skin"] == "default"
    client.put("/api/collection/skin", json={"card_name": "失灵！", "skin": "neon-shiling"})
    frozen = app.state.collection.selected_skin(user["id"], "失灵！")
    assert frozen == "neon-shiling"
    app.state.collection.select_skin(user["id"], "失灵！", "default")
    assert app.state.collection.selected_skin(user["id"], "失灵！") is None


# --------------------------------------------------------------------------- public payloads


def test_public_payloads_include_skin_and_hands_do_not():
    item = ChainItem("p-a", CARD_BY_NAME["看破！"], {}, 0)
    item.mastery_tier = 2
    item.skin_id = "neon-kanpo"
    payload = item.to_dict()
    assert payload["mastery_tier"] == 2
    assert payload["skin_id"] == "neon-kanpo"
    default = ChainItem("p-a", CARD_BY_NAME["看破！"], {}, 0)
    assert "skin_id" not in default.to_dict()
    assert "mastery_tier" not in default.to_dict()

    public = sanitize_preview_item({
        "card": {"name": "看破！"}, "seat": "p2", "negated": False,
        "mastery_tier": 2, "skin_id": "neon-kanpo",
    })
    assert public["mastery_tier"] == 2
    assert public["skin_id"] == "neon-kanpo"
    omitted = sanitize_preview_item({"card": {"name": "看破！"}, "seat": "p2", "negated": False})
    assert "skin_id" not in omitted
    mismatch = sanitize_preview_item({
        "card": {"name": "看破！"}, "seat": "p2", "skin_id": "neon-shiling",
    })
    assert "skin_id" not in mismatch
    assert "skin_id" in PREVIEW_KEYS

    result = ChainResult(card=CARD_BY_NAME["看破！"], caster="p-a", success=True, message="ok",
                         extra={"mastery_tier": 2, "skin_id": "neon-kanpo"})
    dumped = result.to_dict()
    assert dumped["mastery_tier"] == 2 and dumped["skin_id"] == "neon-kanpo"

    cue = public_cue({
        "stage": "join",
        "chain": [{"card": "看破！", "seat": "p2", "negated": False, "mastery_tier": 2, "skin_id": "neon-kanpo"}],
    }, room=None)
    assert cue["chain"][0]["skin_id"] == "neon-kanpo"
    assert cue["chain"][0]["mastery_tier"] == 2
    default_cue = public_cue({
        "stage": "join",
        "chain": [{"card": "看破！", "seat": "p2", "negated": False}],
    }, room=None)
    assert "skin_id" not in default_cue["chain"][0]

    hand = card_payload(CARD_BY_NAME["看破！"])
    assert set(hand) == {"name", "speed", "type", "description"}
    assert "skin_id" not in hand

    class _Card:
        name = "看破！"

    class _Item:
        card = _Card()
        player_id = "someone"
        negated = False
        skin_id = "neon-kanpo"
        mastery_tier = 2

    class _Room:
        chain = [_Item()]
        players = {}

    rows = _chain_items(_Room())
    assert rows == [{"card": "看破！", "side": None, "negated": False}]
    assert "skin_id" not in rows[0]


def test_public_skin_id_helper():
    assert public_skin_id("neon-kanpo", "看破！") == "neon-kanpo"
    assert public_skin_id("neon-kanpo", "失灵！") is None
    assert public_skin_id(None, "看破！") is None
    assert public_skin_id("neon-kanpo", None) is None
