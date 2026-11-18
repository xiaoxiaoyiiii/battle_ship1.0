"""P1-3 掉线 30 秒判负与房间锁：先写应当失败的交错用例。"""
from __future__ import annotations

import asyncio

from battleship.domain.room import RoomPhase, RoomState
from battleship.services.priority import room_action
from test_mystery_tech_flow import stack


def _casual_attacking_stack():
    """非神秘科技、对局中的真实服务栈（与 main 一样接上 forfeit_hook）。"""
    r, rooms, gameplay, magic, battle, publisher, clock = stack()
    r.mystery_tech = False
    r.ranked = False
    r.ban_enabled = False
    r.matchmade = True
    r.state = RoomState.ATTACKING
    r.current_phase = RoomPhase.BATTLE
    r.current_attacker = "a"
    r.round = 1
    r.attacks_remaining = 2
    r.winner = ""
    r.game_over_reason = None
    r.settled = False
    rooms.forfeit_hook = battle.settle_forfeit
    rooms.ended_room_retention_seconds = 3600
    return r, rooms, gameplay, magic, battle, publisher, clock


def _arm_disconnect(room, player_id="b", token=1):
    room.disconnect_seq = token
    room.disconnected[player_id] = {"deadline": 10_000.0, "token": token}


def test_disconnect_timeout_does_not_cancel_win_after_in_flight_attack():
    """对局中攻击已持锁并先击沉取胜时，随后到来的掉线超时不得改写或取消该胜负。"""
    async def run():
        r, rooms, g, magic, battle, pub, clock = _casual_attacking_stack()
        try:
            _arm_disconnect(r, "b", 1)
            started = asyncio.Event()
            release = asyncio.Event()

            async def in_flight_winning_attack():
                async with room_action(r):
                    started.set()
                    await release.wait()
                    await battle.finish_game(r, "a", "b", reason="attacks")

            holder = asyncio.create_task(in_flight_winning_attack())
            await started.wait()
            timeout = asyncio.create_task(rooms._disconnect_timeout(r.id, "b", 1))
            await asyncio.sleep(0)
            assert getattr(r.state, "value", r.state) == RoomState.ATTACKING.value
            release.set()
            await holder
            await timeout
            assert rooms.get_room(r.id) is r
            assert r.state == RoomState.GAME_OVER
            assert r.winner == "a"
            assert r.game_over_reason == "attacks"
            canceled = [data for event, data, target in pub.events if event == "game_canceled"]
            assert canceled == []
        finally:
            await magic.stop()

    asyncio.run(run())


def test_disconnect_timeout_does_not_cancel_an_already_finished_game():
    async def run():
        r, rooms, g, magic, battle, pub, clock = _casual_attacking_stack()
        try:
            await battle.finish_game(r, "b", "a", reason="attacks")
            assert r.state == RoomState.GAME_OVER
            assert r.winner == "b"
            assert r.game_over_reason == "attacks"
            assert r.settled is True
            room_id = r.id
            _arm_disconnect(r, "a", 7)
            await rooms._disconnect_timeout(room_id, "a", 7)
            assert rooms.get_room(room_id) is r
            assert r.state == RoomState.GAME_OVER
            assert r.winner == "b"
            assert r.game_over_reason == "attacks"
            canceled = [data for event, data, target in pub.events if event == "game_canceled"]
            assert canceled == []
        finally:
            await magic.stop()

    asyncio.run(run())


def test_reconnect_then_stale_timeout_does_not_end_game():
    async def run():
        r, rooms, g, magic, battle, pub, clock = _casual_attacking_stack()
        try:
            _arm_disconnect(r, "b", 1)
            # 模拟超时已通过第一道 token 检查后、写终局前，玩家重连并清掉记录。
            # 对 departure_hook 返回 None 的休闲对局，锁外的 pop/终局必须再次核对 token。
            original_hook = rooms.bans.departure_hook

            async def hook_then_reconnect(room, player_id):
                result = await original_hook(room, player_id)
                if result is not None:
                    return result
                room.disconnected.pop(player_id, None)
                return None

            rooms.bans.departure_hook = hook_then_reconnect
            await rooms._disconnect_timeout(r.id, "b", 1)
            assert getattr(r.state, "value", r.state) == RoomState.ATTACKING.value
            assert r.winner in ("", None)
            assert r.game_over_reason in (None, "")
            assert "b" not in r.disconnected
        finally:
            await magic.stop()

    asyncio.run(run())
