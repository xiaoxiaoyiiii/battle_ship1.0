"""每日签到 v1：幂等、沪时换日、里程碑、称号、徽记日帽与二月。"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

_BOOT = Path("/tmp/checkin-boot")
_BOOT.mkdir(parents=True, exist_ok=True)
(_BOOT / "dist").mkdir(exist_ok=True)
(_BOOT / "dist" / "index.html").write_text("<!doctype html><html></html>", encoding="utf-8")
os.environ["SECRET_KEY"] = "test-secret-checkin-v1"
os.environ["BATTLESHIP_DB_PATH"] = str(_BOOT / "boot.db")
os.environ["FRONTEND_DIST"] = str(_BOOT / "dist")
os.environ["FRONTEND_MODE"] = "spa"
os.environ["LOG_LEVEL"] = "ERROR"
os.environ["LOG_JSON"] = "false"
os.environ["DEBUG_ADMIN_USER_IDS"] = ""

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from battleship.config import Settings
from battleship.domain.tasks import BEIJING, periods
from battleship.domain.tide_ash import DAILY_MATCH_CAP, capped_grant
from battleship.main import create_application
from battleship.repositories.migrations import migrate_database
from battleship.repositories.models import TideAshLedger, UserCosmeticReward

STATE_KEYS = {
    "timezone", "server_time", "year", "month", "today", "today_checked",
    "month_count", "checked_days", "days_in_month", "rewards", "title",
    "balance", "show_red_dot",
}
POST_KEYS = STATE_KEYS | {"already_checked", "granted"}
CARD = {
    "title_id": "",
    "tags": [],
    "status_text": "",
    "frame_id": "none",
    "card_bg_id": "deep",
    "show_stats": 1,
    "show_fav_cards": 1,
    "show_history": 0,
    "show_guestbook": 1,
    "show_rank": 1,
    "friend_requests_open": 1,
}


def at(year: int, month: int, day: int, hour: int = 12, minute: int = 0, second: int = 0) -> int:
    return int(datetime(year, month, day, hour, minute, second, tzinfo=BEIJING).timestamp())


class Clock:
    def __init__(self, value: int) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    root = tmp_path_factory.mktemp("checkin")
    database = root / "checkin.db"
    dist = root / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><html></html>", encoding="utf-8")
    migrate_database(database, backup=False, verify=True)
    settings = Settings(
        _env_file=None,
        secret_key=SecretStr("test-secret-checkin-v1"),
        database_path=database,
        frontend_dist=dist,
        daily_puzzles_path=Path("/workspace/config/daily_puzzles.json"),
        log_json=False,
        log_level="ERROR",
    )
    created = create_application(settings)
    app = created.fastapi
    with TestClient(app) as client:
        yield app, client


def set_clock(app, year, month, day, hour=12, minute=0, second=0) -> int:
    value = at(year, month, day, hour, minute, second)
    app.state.checkin.clock = Clock(value)
    return value


def register(client: TestClient, name: str) -> dict:
    response = client.post("/register", json={"username": name, "password": "secret1"})
    assert response.status_code == 200, response.text
    return response.json()["user"]


def post_checkin(client: TestClient, body=None):
    if body is None:
        return client.post("/api/checkin")
    return client.post("/api/checkin", json=body)


def assert_contract(payload: dict, *, post: bool) -> None:
    assert set(payload) == (POST_KEYS if post else STATE_KEYS)
    assert payload["timezone"] == "Asia/Shanghai"
    assert isinstance(payload["server_time"], int)
    assert isinstance(payload["year"], int) and isinstance(payload["month"], int)
    assert isinstance(payload["checked_days"], list)
    assert payload["checked_days"] == sorted(payload["checked_days"])
    assert payload["month_count"] == len(payload["checked_days"])
    assert payload["show_red_dot"] is (not payload["today_checked"])
    assert payload["rewards"]["daily"] == 15
    milestones = payload["rewards"]["milestones"]
    assert [item["days"] for item in milestones] == [7, 14, payload["days_in_month"]]
    assert [item["tide"] for item in milestones] == [80, 150, 300]
    for item in milestones[:2]:
        assert set(item) == {"days", "tide", "reached", "claimed"}
    assert set(milestones[2]) == {"days", "tide", "reached", "claimed", "title"}
    assert set(payload["title"]) == {"id", "name", "owned"}
    if post:
        granted = payload["granted"]
        assert set(granted) == {"daily_tide", "milestone_tide", "milestones_triggered", "title"}


def ledger_rows(app, user_id: str) -> list[TideAshLedger]:
    with app.state.database.unit_of_work() as uow:
        return list(uow.session.scalars(select(TideAshLedger).where(
            TideAshLedger.user_id == user_id,
        )))


def test_guest_is_rejected(stack):
    _app, client = stack
    saved = dict(client.cookies)
    client.cookies.clear()
    try:
        got = client.get("/api/checkin")
        posted = client.post("/api/checkin", json={"today": "2099-01-01"})
    finally:
        client.cookies.update(saved)
    assert got.status_code == 401
    assert posted.status_code == 401
    assert got.json()["error"]["code"] == "unauthorized"
    assert posted.json()["error"]["code"] == "unauthorized"


def test_same_day_is_idempotent_and_ignores_client_date(stack):
    app, client = stack
    user = register(client, "checkin_once")
    moment = set_clock(app, 2026, 11, 7, 15, 30)
    preview = client.get("/api/checkin")
    assert preview.status_code == 200
    before = preview.json()
    assert_contract(before, post=False)
    assert before["today"] == "2026-11-07"
    assert before["server_time"] == moment
    assert before["today_checked"] is False
    assert before["show_red_dot"] is True
    assert before["month_count"] == 0
    assert before["balance"] == 0
    assert before["title"] == {
        "id": "checkin_2026_11", "name": "潮汐签到·2026年11月", "owned": False,
    }

    first = post_checkin(client, {"today": "1999-01-01", "year": 1999, "month": 1})
    assert first.status_code == 200
    body = first.json()
    assert_contract(body, post=True)
    assert body["already_checked"] is False
    assert body["today"] == "2026-11-07"
    assert body["granted"] == {
        "daily_tide": 15, "milestone_tide": 0, "milestones_triggered": [], "title": None,
    }
    assert body["today_checked"] is True
    assert body["show_red_dot"] is False
    assert body["month_count"] == 1
    assert body["checked_days"] == [7]
    assert body["balance"] == 15

    second = post_checkin(client, {"today": "2026-11-08"})
    assert second.status_code == 200
    again = second.json()
    assert_contract(again, post=True)
    assert again["already_checked"] is True
    assert again["granted"] == {
        "daily_tide": 0, "milestone_tide": 0, "milestones_triggered": [], "title": None,
    }
    assert again["balance"] == 15
    assert again["month_count"] == 1
    assert again["checked_days"] == [7]
    kinds = {row.source_kind for row in ledger_rows(app, user["id"])}
    assert kinds == {"checkin"}
    shop = client.get("/api/shop")
    assert shop.status_code == 200
    assert shop.json()["balance"] == 15


def test_match_cap_ignores_checkin_tide(stack):
    app, client = stack
    user = register(client, "checkin_cap")
    moment = set_clock(app, 2026, 11, 8, 9)
    posted = post_checkin(client)
    assert posted.status_code == 200
    assert posted.json()["balance"] == 15
    window = periods(moment)["daily"]
    start, end = window["next_reset_at"] - 86400, window["next_reset_at"]
    with app.state.database.unit_of_work() as uow:
        match_granted = uow.tide_ash.granted_between(user["id"], "match_tide", start, end)
        checkin_granted = uow.tide_ash.granted_between(user["id"], "checkin", start, end)
        assert match_granted == 0
        assert checkin_granted == 15
        assert capped_grant(DAILY_MATCH_CAP, match_granted, DAILY_MATCH_CAP) == 60
        assert uow.tide_ash.apply_once(user["id"], "match_tide", "match-cap", 60, now=moment)
        assert uow.tide_ash.granted_between(user["id"], "match_tide", start, end) == 60
        assert capped_grant(12, 60, DAILY_MATCH_CAP) == 0
        assert uow.tide_ash.balance(user["id"]) == 75
    assert client.get("/api/shop").json()["balance"] == 75
    wallet = client.get("/api/battle-pass").json()["wallet"]
    assert wallet["daily_cap"] == 60
    assert wallet["balance"] == 75


def test_midnight_skip_and_month_reset(stack):
    app, client = stack
    register(client, "checkin_month")
    for day in range(1, 7):
        set_clock(app, 2026, 11, day)
        body = post_checkin(client).json()
        assert body["already_checked"] is False
        assert body["granted"]["daily_tide"] == 15
        assert body["granted"]["milestones_triggered"] == []
        assert body["month_count"] == day
    set_clock(app, 2026, 11, 7, 23, 59, 50)
    seventh = post_checkin(client).json()
    assert seventh["granted"] == {
        "daily_tide": 15, "milestone_tide": 80, "milestones_triggered": [7], "title": None,
    }
    assert seventh["month_count"] == 7
    assert seventh["rewards"]["milestones"][0]["reached"] is True
    assert seventh["rewards"]["milestones"][0]["claimed"] is True
    assert seventh["balance"] == 7 * 15 + 80
    repeat = post_checkin(client).json()
    assert repeat["already_checked"] is True
    assert repeat["granted"]["daily_tide"] == 0
    assert repeat["granted"]["milestone_tide"] == 0
    assert repeat["balance"] == seventh["balance"]

    set_clock(app, 2026, 11, 8, 0, 0, 0)
    eighth = post_checkin(client).json()
    assert eighth["already_checked"] is False
    assert eighth["today"] == "2026-11-08"
    assert eighth["granted"]["daily_tide"] == 15
    assert eighth["granted"]["milestone_tide"] == 0
    assert eighth["month_count"] == 8

    set_clock(app, 2026, 11, 10, 8)
    skipped = post_checkin(client).json()
    assert skipped["month_count"] == 9
    assert skipped["checked_days"] == [1, 2, 3, 4, 5, 6, 7, 8, 10]
    assert 9 not in skipped["checked_days"]

    set_clock(app, 2026, 12, 1, 0, 5)
    december = post_checkin(client).json()
    assert december["year"] == 2026 and december["month"] == 12
    assert december["today"] == "2026-12-01"
    assert december["month_count"] == 1
    assert december["checked_days"] == [1]
    assert december["days_in_month"] == 31
    assert december["granted"] == {
        "daily_tide": 15, "milestone_tide": 0, "milestones_triggered": [], "title": None,
    }
    assert december["rewards"]["milestones"][0]["reached"] is False
    assert december["rewards"]["milestones"][0]["claimed"] is False
    assert december["rewards"]["milestones"][2]["days"] == 31
    assert december["rewards"]["milestones"][2]["tide"] == 300
    assert december["rewards"]["milestones"][2]["reached"] is False
    assert december["rewards"]["milestones"][2]["claimed"] is False
    assert december["title"]["id"] == "checkin_2026_12"
    assert december["title"]["owned"] is False
    assert december["balance"] == seventh["balance"] + 15 + 15 + 15


def test_milestones_grant_once_and_title_is_equippable(stack):
    app, client = stack
    user = register(client, "checkin_full")
    equipped = dict(CARD, title_id="rookie")
    assert client.post("/api/profile/card", json=equipped).status_code == 200
    balances = {}
    grants = {}
    for day in range(1, 31):
        set_clock(app, 2026, 1, day, 10)
        body = post_checkin(client).json()
        balances[day] = body["balance"]
        grants[day] = body["granted"]
        assert body["already_checked"] is False
        assert body["granted"]["daily_tide"] == 15
        assert body["rewards"]["milestones"][2]["days"] == 31
        repeat = post_checkin(client).json()
        assert repeat["already_checked"] is True
        assert repeat["granted"]["daily_tide"] == 0
        assert repeat["granted"]["milestone_tide"] == 0
        assert repeat["granted"]["title"] is None
        assert repeat["balance"] == body["balance"]
    assert grants[7] == {
        "daily_tide": 15, "milestone_tide": 80, "milestones_triggered": [7], "title": None,
    }
    assert grants[14] == {
        "daily_tide": 15, "milestone_tide": 150, "milestones_triggered": [14], "title": None,
    }
    assert grants[30] == {
        "daily_tide": 15, "milestone_tide": 0, "milestones_triggered": [], "title": None,
    }
    assert balances[7] - balances[6] == 15 + 80
    assert balances[14] - balances[13] == 15 + 150
    assert balances[30] - balances[29] == 15
    assert balances[30] == 30 * 15 + 80 + 150

    set_clock(app, 2026, 1, 30, 10)
    before_full = client.get("/api/checkin").json()
    assert before_full["rewards"]["milestones"][2]["days"] == 31
    assert before_full["rewards"]["milestones"][2]["tide"] == 300
    assert before_full["rewards"]["milestones"][2]["reached"] is False
    assert before_full["rewards"]["milestones"][2]["claimed"] is False
    assert before_full["title"]["owned"] is False
    assert client.get("/api/profile").json()["profile"]["title_id"] == "rookie"

    set_clock(app, 2026, 1, 31, 10)
    body = post_checkin(client).json()
    assert body["already_checked"] is False
    assert body["rewards"]["milestones"][2]["days"] == 31
    assert body["granted"] == {
        "daily_tide": 15, "milestone_tide": 300, "milestones_triggered": [31],
        "title": {"id": "checkin_2026_01", "name": "潮汐签到·2026年1月"},
    }
    assert body["balance"] == 31 * 15 + 80 + 150 + 300
    repeat = post_checkin(client).json()
    assert repeat["already_checked"] is True
    assert repeat["granted"]["milestone_tide"] == 0
    assert repeat["granted"]["title"] is None
    assert repeat["balance"] == body["balance"]

    current = client.get("/api/checkin").json()
    assert current["rewards"]["milestones"][0]["claimed"] is True
    assert current["rewards"]["milestones"][1]["claimed"] is True
    assert current["rewards"]["milestones"][2]["days"] == 31
    assert current["rewards"]["milestones"][2]["reached"] is True
    assert current["rewards"]["milestones"][2]["claimed"] is True
    assert current["rewards"]["milestones"][2]["title"] == {
        "id": "checkin_2026_01", "name": "潮汐签到·2026年1月",
    }
    assert current["title"]["owned"] is True
    profile = client.get("/api/profile").json()["profile"]
    assert profile["title_id"] == "rookie"
    catalog = {item["id"]: item for item in profile["catalog"]["titles"]}
    assert catalog["checkin_2026_01"]["unlocked"] is True
    assert catalog["checkin_2026_01"]["name"] == "潮汐签到·2026年1月"

    saved = client.post("/api/profile/card", json=dict(CARD, title_id="checkin_2026_01"))
    assert saved.status_code == 200, saved.text
    assert saved.json()["profile"]["title_id"] == "checkin_2026_01"
    public = client.get("/user_stats", params={"username": user["username"]}).json()["stats"]
    assert public["title_id"] == "checkin_2026_01"
    assert public["title_name"] == "潮汐签到·2026年1月"

    with app.state.database.unit_of_work() as uow:
        sources = list(uow.session.scalars(select(TideAshLedger.source_id).where(
            TideAshLedger.user_id == user["id"],
            TideAshLedger.source_kind == "checkin",
            TideAshLedger.source_id.like("milestone:2026-01:%"),
        )))
        assert sorted(sources) == ["milestone:2026-01:14", "milestone:2026-01:31", "milestone:2026-01:7"]
        owned = uow.session.get(UserCosmeticReward, (user["id"], "title", "checkin_2026_01"))
        assert owned is not None


def _february(stack, username: str, year: int, days: int):
    app, client = stack
    user = register(client, username)
    assert client.post("/api/profile/card", json=dict(CARD, title_id="rookie")).status_code == 200
    title = {"id": f"checkin_{year}_02", "name": f"潮汐签到·{year}年2月"}
    last = None
    for day in range(1, days + 1):
        set_clock(app, year, 2, day, 11)
        last = post_checkin(client)
        assert last.status_code == 200
        body = last.json()
        assert body["already_checked"] is False
        assert body["days_in_month"] == days
        assert body["month_count"] == day
        assert body["rewards"]["milestones"][2]["days"] == days
        assert body["rewards"]["milestones"][2]["tide"] == 300
        if day < days:
            assert body["title"]["owned"] is False
            assert body["rewards"]["milestones"][2]["reached"] is False
            assert body["rewards"]["milestones"][2]["claimed"] is False
            assert body["granted"]["title"] is None
            if day in (7, 14):
                assert body["granted"]["milestones_triggered"] == [day]
            else:
                assert body["granted"]["milestone_tide"] == 0
                assert body["granted"]["milestones_triggered"] == []
    body = last.json()
    assert body["checked_days"] == list(range(1, days + 1))
    assert body["granted"] == {
        "daily_tide": 15, "milestone_tide": 300, "milestones_triggered": [days], "title": title,
    }
    assert body["rewards"]["milestones"][2]["reached"] is True
    assert body["rewards"]["milestones"][2]["claimed"] is True
    assert body["title"]["owned"] is True
    assert body["balance"] == days * 15 + 80 + 150 + 300
    assert client.get("/api/profile").json()["profile"]["title_id"] == "rookie"
    saved = client.post("/api/profile/card", json=dict(CARD, title_id=title["id"]))
    assert saved.status_code == 200, saved.text
    assert saved.json()["profile"]["title_id"] == title["id"]
    public = client.get("/user_stats", params={"username": user["username"]}).json()["stats"]
    assert public["title_name"] == title["name"]
    with app.state.database.unit_of_work() as uow:
        source = uow.session.scalar(select(TideAshLedger.source_id).where(
            TideAshLedger.user_id == user["id"],
            TideAshLedger.source_kind == "checkin",
            TideAshLedger.source_id == f"milestone:{year}-02:{days}",
        ))
        assert source == f"milestone:{year}-02:{days}"


def test_february_full_attendance_grants_title(stack):
    _february(stack, "checkin_feb", 2026, 28)
    _february(stack, "checkin_leap", 2024, 29)
