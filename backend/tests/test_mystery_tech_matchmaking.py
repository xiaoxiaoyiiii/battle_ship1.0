"""神秘科技大乱斗匹配队列、建房标志与休闲结算。"""
from __future__ import annotations

import asyncio

from test_skin_gacha import stack as application, register

from battleship.domain.lobby.rules import lobby_counters
from battleship.domain.room import PlayerShip, Position, RoomState, room_match_mode
from battleship.domain.settlement import settlement_facts
from battleship.domain.tide_ash import MATCH_COMPLETION_TIDE, MATCH_WIN_TIDE
from battleship.repositories.models import TideAshLedger, UserRank
from battleship.services.matchmaking import (
    MATCH_MODE_CASUAL,
    MATCH_MODE_MYSTERY_TECH,
    MATCH_MODE_RANKED,
    MatchmakingService,
    normalize_match_mode,
)
from battleship.services.rooms import Connection, RoomService


class RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict, dict]] = []

    async def emit(self, event: str, data: dict, *, to=None, room=None) -> None:
        self.events.append((event, data, {"to": to, "room": room}))

    async def enter_room(self, sid: str, room: str) -> None:
        self.events.append(("enter_room", {"sid": sid, "room": room}, {}))

    async def leave_room(self, sid: str, room: str) -> None:
        self.events.append(("leave_room", {"sid": sid, "room": room}, {}))


def make_service() -> tuple[MatchmakingService, RoomService, RecordingPublisher]:
    rooms = RoomService()
    service = MatchmakingService(rooms)
    publisher = RecordingPublisher()
    service.bind(publisher)
    return service, rooms, publisher


def guest(sid: str, name: str) -> Connection:
    return Connection(sid=sid, username=name)


def account(sid: str, user_id: str, name: str) -> Connection:
    return Connection(sid=sid, user_id=user_id, username=name)


def queued_modes(rooms: RoomService) -> list[str]:
    return [str(entry.get("mode")) for entry in rooms.match_queue]


def test_normalize_match_mode_only_accepts_exact_literals():
    assert normalize_match_mode("mystery_tech") == MATCH_MODE_MYSTERY_TECH
    assert normalize_match_mode("ranked") == MATCH_MODE_RANKED
    assert normalize_match_mode("casual") == MATCH_MODE_CASUAL
    # 大小写或拼写错误不得进入神秘科技或排位池，沿用既有 typo 安全默认。
    assert normalize_match_mode("Mystery_Tech") == MATCH_MODE_CASUAL
    assert normalize_match_mode("MYSTERY_TECH") == MATCH_MODE_CASUAL
    assert normalize_match_mode(None) == MATCH_MODE_CASUAL
    assert normalize_match_mode("custom") == MATCH_MODE_CASUAL


def test_enqueue_and_cancel_mystery_tech():
    async def run():
        service, rooms, publisher = make_service()
        result = await service.find_match(
            guest("sid-a", "甲"),
            {"mode": "mystery_tech", "player_name": "甲"},
        )
        assert result == {"status": "success", "message": "开始寻找匹配"}
        assert queued_modes(rooms) == ["mystery_tech"]
        queued = [event for event in publisher.events if event[0] == "match_queued"]
        assert queued[-1][1] == {
            "status": "success",
            "message": "已加入匹配队列",
            "mode": "mystery_tech",
        }
        assert queued[-1][2]["to"] == "sid-a"

        canceled = await service.cancel_match(guest("sid-a", "甲"), {})
        assert canceled == {"status": "success", "message": "已取消匹配"}
        assert rooms.match_queue == []
        last = [event for event in publisher.events if event[0] == "match_canceled"][-1]
        assert last[1] == {"status": "success", "message": "已取消匹配"}
        assert last[2]["to"] == "sid-a"

        again = await service.find_match(
            guest("sid-a", "甲"),
            {"mode": "mystery_tech", "player_name": "甲"},
        )
        assert again["status"] == "success"
        dup = await service.find_match(
            guest("sid-a", "甲"),
            {"mode": "mystery_tech", "player_name": "甲"},
        )
        assert dup == {"status": "error", "message": "你已经在匹配队列中"}
    asyncio.run(run())


def test_pair_sets_contract_room_flags_and_skips_weekly_mutations():
    async def run():
        service, rooms, publisher = make_service()
        first = await service.find_match(guest("sid-a", "甲"), {"mode": "mystery_tech", "player_name": "甲"})
        second = await service.find_match(guest("sid-b", "乙"), {"mode": "mystery_tech", "player_name": "乙"})
        assert first["status"] == "success" and second["status"] == "success"
        assert rooms.match_queue == []
        assert len(rooms.rooms) == 1
        room = next(iter(rooms.rooms.values()))
        assert room.mystery_tech is True
        assert room.ranked is False
        assert room.matchmade is True
        assert room.ban_enabled is False
        assert room.mutation_ids == []
        assert not room.mutation_token
        assert room.mutation_entries == []
        assert room_match_mode(room) == "mystery_tech"
        assert room.state == RoomState.PLACING_SHIPS
        assert set(room.players) == {"sid-a", "sid-b"}
        states = [data for event, data, _target in publisher.events if event == "game_state"]
        assert len(states) == 2
        assert all(item["mode"] == "mystery_tech" and item["ranked"] is False for item in states)
        assert all(item["state"] == RoomState.PLACING_SHIPS.value for item in states)
        assert all(item["mutations"] is None for item in states)
    asyncio.run(run())


def test_mystery_tech_does_not_mix_with_casual_or_ranked():
    async def run():
        service, rooms, _publisher = make_service()
        await service.find_match(guest("casual-1", "休1"), {"mode": "casual", "player_name": "休1"})
        await service.find_match(
            account("ranked-1", "user-r1", "排1"),
            {"mode": "ranked", "player_name": "排1"},
        )
        await service.find_match(guest("tech-1", "科1"), {"mode": "mystery_tech", "player_name": "科1"})
        assert queued_modes(rooms) == ["casual", "ranked", "mystery_tech"]
        assert rooms.rooms == {}

        await service.find_match(guest("tech-2", "科2"), {"mode": "mystery_tech", "player_name": "科2"})
        assert queued_modes(rooms) == ["casual", "ranked"]
        assert len(rooms.rooms) == 1
        room = next(iter(rooms.rooms.values()))
        assert room.mystery_tech is True
        assert set(room.players) == {"tech-1", "tech-2"}

        await service.find_match(guest("casual-2", "休2"), {"mode": "casual", "player_name": "休2"})
        assert "casual" not in queued_modes(rooms)
        assert queued_modes(rooms) == ["ranked"]
        casual_rooms = [item for item in rooms.rooms.values() if not item.mystery_tech and not item.ranked]
        assert len(casual_rooms) == 1
        assert casual_rooms[0].matchmade is True
        assert set(casual_rooms[0].players) == {"casual-1", "casual-2"}
    asyncio.run(run())


def test_lobby_counters_split_mystery_tech_out_of_casual():
    queue = [
        {"sid": "c1", "mode": "casual"},
        {"sid": "c2", "mode": "casual"},
        {"sid": "r1", "mode": "ranked"},
        {"sid": "t1", "mode": "mystery_tech"},
        {"sid": "t2", "mode": "mystery_tech"},
    ]
    counters = lobby_counters([], {}, queue)
    assert counters.queue == {"casual": 2, "ranked": 1, "mystery_tech": 2}


def test_matchmade_mystery_tech_uses_casual_rewards_and_forfeit_skips_mmr(application):
    async def run():
        app, client = application
        user_a = register(client, "mt_queue_a")
        user_b = register(client, "mt_queue_b")
        service = app.state.matchmaking
        # 组合根绑的是真实 Socket.IO；测试连接没有实际 sid，改用记录型发布器完成入队与建房。
        original = service._publisher
        service.bind(RecordingPublisher())
        try:
            first = await service.find_match(
                account("sid-a", user_a["id"], "mt_queue_a"),
                {"mode": "mystery_tech", "player_name": "mt_queue_a"},
            )
            second = await service.find_match(
                account("sid-b", user_b["id"], "mt_queue_b"),
                {"mode": "mystery_tech", "player_name": "mt_queue_b"},
            )
        finally:
            service.bind(original)
        assert first["status"] == "success" and second["status"] == "success"
        rooms = [
            room for room in app.state.rooms.rooms.values()
            if room.mystery_tech and room.matchmade
        ]
        assert len(rooms) == 1
        room = rooms[0]
        assert room.ranked is False
        assert room.ban_enabled is False
        assert room.mutation_ids == []
        assert room_match_mode(room) == "mystery_tech"

        for player in room.players.values():
            player.ships = [PlayerShip(positions=[Position(0, 0), Position(1, 0)])]
            player.remaining_ships = 1
        room.ban_initial_placement_complete = True
        assert await app.state.gameplay.mystery_tech.begin(room)

        result = await app.state.battle.surrender(
            Connection(sid="sid-a", user_id=user_a["id"]),
            {"room_id": room.id, "player_id": "sid-a"},
        )
        assert result["status"] == "success" and room.winner == "sid-b"
        facts = settlement_facts(room, "sid-b", "sid-a")
        assert facts.mode == "casual"
        assert facts.count_stats is True
        assert facts.rewards_eligible is True
        assert room.settlement_result.ok and room.settlement_result.match_id

        with app.state.database.unit_of_work() as uow:
            match = uow.matches.get(room.settlement_result.match_id)
            assert match.mode == "casual" and match.rewards_eligible
            assert uow.users.get(user_a["id"]).losses == 1
            assert uow.users.get(user_b["id"]).wins == 1
            # 总余额还可能含图鉴点亮等其他流水；休闲对局徽记只核 match_tide。
            loser_tide = uow.session.query(TideAshLedger).filter_by(
                user_id=user_a["id"], source_kind="match_tide"
            ).all()
            winner_tide = uow.session.query(TideAshLedger).filter_by(
                user_id=user_b["id"], source_kind="match_tide"
            ).all()
            assert [(row.source_id, row.delta) for row in loser_tide] == [
                (room.settlement_result.match_id, MATCH_COMPLETION_TIDE)
            ]
            assert [(row.source_id, row.delta) for row in winner_tide] == [
                (room.settlement_result.match_id, MATCH_COMPLETION_TIDE + MATCH_WIN_TIDE)
            ]
            for user in (user_a, user_b):
                rank = uow.session.get(UserRank, user["id"])
                assert rank is None or (
                    rank.points == 0 and rank.ranked_wins == 0 and rank.ranked_losses == 0
                )
            assert uow.collection.state(user_a["id"]).get("matches") == 1
            assert uow.collection.state(user_b["id"]).get("matches") == 1
            assert uow.collection.state(user_b["id"]).get("wins") == 1
            assert uow.collection.state(user_a["id"]).get("wins", 0) == 0
    asyncio.run(run())
